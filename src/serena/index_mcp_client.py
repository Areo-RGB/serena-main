"""Small synchronous client for the JetBrains Index MCP server.

Serena's tools are synchronous. The Index MCP plugin's primary endpoint is stateless
Streamable HTTP, and explicitly permits ``tools/call`` without a prior ``initialize``.
Using the wire protocol directly therefore avoids nesting an async MCP client inside
Serena's synchronous tool execution path.
"""

from __future__ import annotations

import itertools
import json
import os
from dataclasses import dataclass
from typing import Any

import requests

DEFAULT_INDEX_MCP_URL = "http://127.0.0.1:29170/index-mcp/streamable-http"
DEFAULT_TIMEOUT_SECONDS = 30.0
DEFAULT_MAX_PAGINATED_ITEMS = 10_000


class IndexMcpError(RuntimeError):
    """Raised when the Index MCP endpoint cannot execute a tool call."""


@dataclass(frozen=True)
class PaginatedToolResult:
    items: list[dict[str, Any]]
    metadata: dict[str, Any]
    truncated: bool = False


class IndexMcpClient:
    """Synchronous JSON-RPC client for the stateless Index MCP HTTP endpoint."""

    _ids = itertools.count(1)

    def __init__(self, project_path: str, url: str | None = None, timeout_seconds: float | None = None) -> None:
        self.project_path = project_path
        self.url = url or os.environ.get("SERENA_INDEX_MCP_URL", DEFAULT_INDEX_MCP_URL)
        configured_timeout = os.environ.get("SERENA_INDEX_MCP_TIMEOUT_SECONDS")
        self.timeout_seconds = timeout_seconds or (float(configured_timeout) if configured_timeout else DEFAULT_TIMEOUT_SECONDS)

    def call_tool(self, tool_name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any] | str:
        args = {"project_path": self.project_path}
        if arguments:
            args.update(arguments)

        request_id = next(self._ids)
        payload = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": "tools/call",
            "params": {"name": tool_name, "arguments": args},
        }
        headers = {
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
        }

        try:
            response = requests.post(self.url, json=payload, headers=headers, timeout=self.timeout_seconds)
            response.raise_for_status()
        except requests.RequestException as exc:
            raise IndexMcpError(
                f"Could not call Index MCP at {self.url}: {exc}. "
                "Make sure the JetBrains Index MCP plugin is running and the target project is open."
            ) from exc

        try:
            envelope = response.json()
        except ValueError:
            envelope = self._parse_sse_envelope(response.text)
            if envelope is None:
                raise IndexMcpError(f"Index MCP returned an unreadable HTTP response for {tool_name}: {response.text[:500]}")

        if not isinstance(envelope, dict):
            raise IndexMcpError(f"Index MCP returned an invalid JSON-RPC envelope for {tool_name}: {envelope!r}")
        if "error" in envelope:
            raise IndexMcpError(f"Index MCP JSON-RPC error for {tool_name}: {envelope['error']}")

        result = envelope.get("result")
        if not isinstance(result, dict):
            raise IndexMcpError(f"Index MCP returned an invalid result for {tool_name}: {result!r}")

        content = result.get("content", [])
        text_parts = [part.get("text", "") for part in content if isinstance(part, dict) and part.get("type") == "text"]
        text = "\n".join(part for part in text_parts if part)

        if result.get("isError"):
            hint = ""
            lower_text = text.lower()
            if "disabled" in lower_text:
                hint = (
                    " Enable this tool in JetBrains: Settings > Tools > Index MCP Server > Exposed Tools."
                )
            raise IndexMcpError(f"Index MCP tool {tool_name} failed: {text or result!r}.{hint}")

        # The plugin's default response format is JSON text. A user can globally select
        # TOON; Serena needs structured payloads for the adapter layer, so fail clearly.
        if not text:
            return {}
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return text
        return parsed

    @staticmethod
    def _parse_sse_envelope(body: str) -> dict[str, Any] | None:
        """Extract a JSON-RPC message from a completed Streamable HTTP SSE response."""
        candidate: dict[str, Any] | None = None
        for raw_line in body.splitlines():
            line = raw_line.strip()
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if not data or data == "[DONE]":
                continue
            try:
                parsed = json.loads(data)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict) and ("result" in parsed or "error" in parsed):
                candidate = parsed
        return candidate

    def call_json_tool(self, tool_name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        result = self.call_tool(tool_name, arguments)
        if isinstance(result, str):
            raise IndexMcpError(
                f"Index MCP tool {tool_name} returned non-JSON text. "
                "Set Index MCP Server > Response format to JSON in JetBrains for Serena integration. "
                f"Response: {result[:500]}"
            )
        return result

    def call_file_structure(self, relative_path: str) -> dict[str, Any] | None:
        """Call ``ide_file_structure`` while handling its documented empty-file text result."""
        result = self.call_tool("ide_file_structure", {"file": relative_path})
        if isinstance(result, dict):
            return result
        if result.startswith("File is empty or has no parseable structure."):
            return None
        raise IndexMcpError(
            "Index MCP ide_file_structure returned non-JSON text. "
            "Set Index MCP Server > Response format to JSON in JetBrains for Serena integration. "
            f"Response: {result[:500]}"
        )

    def call_paginated_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        collection_key: str,
        *,
        max_items: int | None = None,
        page_size: int = 500,
    ) -> PaginatedToolResult:
        """Collect pages from an Index MCP search result.

        ``max_items=None`` preserves Serena's effectively-unbounded search semantics up to a
        defensive 10k result ceiling so a broad query cannot lock a Serena MCP worker forever.
        """

        hard_limit = DEFAULT_MAX_PAGINATED_ITEMS if max_items is None else min(max_items, DEFAULT_MAX_PAGINATED_ITEMS)
        hard_limit = max(1, hard_limit)
        page_size = max(1, min(page_size, 500, hard_limit))

        first_args = dict(arguments)
        first_args["pageSize"] = page_size
        page = self.call_json_tool(tool_name, first_args)
        items = list(page.get(collection_key, []))
        metadata = dict(page)
        metadata.pop(collection_key, None)

        seen_cursors: set[str] = set()
        while page.get("hasMore") and page.get("nextCursor") and len(items) < hard_limit:
            cursor = str(page["nextCursor"])
            if cursor in seen_cursors:
                break
            seen_cursors.add(cursor)
            page = self.call_json_tool(tool_name, {"cursor": cursor, "pageSize": min(page_size, hard_limit - len(items))})
            page_items = page.get(collection_key, [])
            if isinstance(page_items, list):
                items.extend(page_items)
            metadata.update({k: v for k, v in page.items() if k != collection_key})

        truncated = bool(page.get("hasMore")) or len(items) > hard_limit
        return PaginatedToolResult(items=items[:hard_limit], metadata=metadata, truncated=truncated)

# File-structure output is intentionally human-readable in the plugin. These helpers
# recover enough structure for Serena's legacy get_symbols_overview/find_symbol shapes.
_STRUCTURE_KIND_MAP = {
    "class": "Class",
    "interface": "Interface",
    "enum": "Enum",
    "@interface": "Interface",
    "record": "Struct",
    "object": "Class",
    "trait": "Interface",
    "constructor": "Constructor",
    "constant": "Constant",
    "enum case": "EnumMember",
    "namespace": "Namespace",
    "package": "Package",
    "module": "Module",
    "typealias": "TypeParameter",
    "var": "Variable",
    "heading": "String",
    "include": "File",
    "method": "Method",
    "fun": "Method",
    "def": "Function",
    "function": "Function",
    "field": "Field",
    "variable": "Variable",
    "val": "Property",
    "property": "Property",
    "unknown": "Object",
}
_STRUCTURE_KINDS = sorted(_STRUCTURE_KIND_MAP, key=len, reverse=True)
_STRUCTURE_MODIFIERS = {
    "public", "private", "protected", "internal", "static", "final", "abstract", "open", "sealed",
    "override", "virtual", "async", "suspend", "const", "readonly", "lateinit", "data", "inline",
    "external", "native", "synchronized", "transient", "volatile", "export", "default",
}


def _structure_name(rest: str) -> str:
    tokens = rest.strip().split()
    while tokens and tokens[0].lower() in _STRUCTURE_MODIFIERS:
        tokens.pop(0)
    if not tokens:
        return "unknown"
    token = tokens[0]
    for sep in ("(", "<", ":", "{"):
        token = token.split(sep, 1)[0]
    return token.rstrip(";,=") or "unknown"


def parse_file_structure_tree(structure: str) -> list[dict[str, Any]]:
    """Parse ``ide_file_structure``'s formatted tree into Serena-like symbol dicts."""
    import re

    line_re = re.compile(r"^(?P<indent> *)(?P<body>.+?) \((?:lines (?P<start>\d+)-(?P<end>\d+)|line (?P<single>\d+))\)$")
    roots: list[dict[str, Any]] = []
    stack: list[tuple[int, dict[str, Any]]] = []
    lines = structure.splitlines()
    # First non-empty line is the file-name header, not a node.
    header_skipped = False
    for raw in lines:
        if not raw.strip():
            continue
        if not header_skipped:
            header_skipped = True
            continue
        match = line_re.match(raw)
        if not match:
            continue
        body = match.group("body")
        kind_token = next((kind for kind in _STRUCTURE_KINDS if body == kind or body.startswith(kind + " ")), None)
        if kind_token is None:
            continue
        rest = body[len(kind_token) :].strip()
        start = int(match.group("start") or match.group("single"))
        end = int(match.group("end") or match.group("single"))
        node: dict[str, Any] = {
            "name": _structure_name(rest),
            "kind": _STRUCTURE_KIND_MAP[kind_token],
            "start_line": start,
            "end_line": end,
            "children": [],
        }
        indent = len(match.group("indent")) // 2
        while stack and stack[-1][0] >= indent:
            stack.pop()
        if stack:
            stack[-1][1]["children"].append(node)
        else:
            roots.append(node)
        stack.append((indent, node))
    return roots


def find_structure_node(nodes: list[dict[str, Any]], *, line: int, name: str | None = None) -> dict[str, Any] | None:
    """Find the narrowest structure node containing a 1-based line, preferring name matches."""
    candidates: list[dict[str, Any]] = []

    def visit(node: dict[str, Any]) -> None:
        if int(node.get("start_line", 0)) <= line <= int(node.get("end_line", 0)):
            candidates.append(node)
            for child in node.get("children", []):
                if isinstance(child, dict):
                    visit(child)

    for root in nodes:
        visit(root)
    if name:
        named = [node for node in candidates if str(node.get("name")) == name]
        if named:
            candidates = named
    if not candidates:
        return None
    return min(candidates, key=lambda node: int(node.get("end_line", line)) - int(node.get("start_line", line)))
