"""Synchronous client for Code Intelligence MCP (intellij-mcp).

The JetBrains plugin exposes a small HTTP MCP endpoint at ``/mcp``. Serena keeps
its own public 0-based coordinate convention; this client only handles transport
and leaves coordinate adaptation to the Serena tools.
"""

from __future__ import annotations

import itertools
import json
import os
from typing import Any

import requests

DEFAULT_INTELLIJ_MCP_URL = "http://127.0.0.1:9876/mcp"
DEFAULT_TIMEOUT_SECONDS = 30.0


class IntellijMcpError(RuntimeError):
    """Raised when Code Intelligence MCP cannot execute a tool call."""


class IntellijMcpClient:
    """Small synchronous JSON-RPC client for the intellij-mcp HTTP endpoint."""

    _ids = itertools.count(1)

    def __init__(self, project_path: str, url: str | None = None, timeout_seconds: float | None = None) -> None:
        self.project_path = os.path.abspath(project_path)
        self.url = url or os.environ.get("SERENA_INTELLIJ_MCP_URL", DEFAULT_INTELLIJ_MCP_URL)
        configured_timeout = os.environ.get("SERENA_INTELLIJ_MCP_TIMEOUT_SECONDS")
        self.timeout_seconds = timeout_seconds or (float(configured_timeout) if configured_timeout else DEFAULT_TIMEOUT_SECONDS)

    def absolute_file_path(self, path: str) -> str:
        return path if os.path.isabs(path) else os.path.abspath(os.path.join(self.project_path, path))

    def relative_file_path(self, path: str) -> str:
        if not path:
            return ""
        try:
            return os.path.relpath(path, self.project_path).replace("\\", "/")
        except ValueError:
            return path.replace("\\", "/")

    def call_tool(self, tool_name: str, arguments: dict[str, Any] | None = None) -> Any:
        args = dict(arguments or {})
        args.setdefault("projectPath", self.project_path)

        payload = {
            "jsonrpc": "2.0",
            "id": next(self._ids),
            "method": "tools/call",
            "params": {"name": tool_name, "arguments": args},
        }
        try:
            response = requests.post(
                self.url,
                json=payload,
                headers={"Accept": "application/json", "Content-Type": "application/json"},
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            raise IntellijMcpError(
                f"Could not call Code Intelligence MCP at {self.url}: {exc}. "
                "Make sure the JetBrains IDE is running, the project is open, and the Code Intelligence MCP plugin is started."
            ) from exc

        try:
            envelope = response.json()
        except ValueError as exc:
            raise IntellijMcpError(f"Code Intelligence MCP returned non-JSON HTTP data for {tool_name}: {response.text[:500]}") from exc

        if not isinstance(envelope, dict):
            raise IntellijMcpError(f"Code Intelligence MCP returned an invalid JSON-RPC envelope: {envelope!r}")
        if "error" in envelope:
            error = envelope["error"]
            hint = ""
            if isinstance(error, dict) and error.get("code") == -32004:
                hint = " JetBrains is still indexing; wait for dumb mode to finish and retry."
            raise IntellijMcpError(f"Code Intelligence MCP {tool_name} failed: {error!r}.{hint}")

        result = envelope.get("result")
        if not isinstance(result, dict):
            raise IntellijMcpError(f"Code Intelligence MCP returned an invalid result for {tool_name}: {result!r}")

        content = result.get("content", [])
        text = "\n".join(
            str(part.get("text", ""))
            for part in content
            if isinstance(part, dict) and part.get("type") == "text" and part.get("text")
        )
        if not text:
            return None
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise IntellijMcpError(f"Code Intelligence MCP returned non-JSON tool content for {tool_name}: {text[:500]}") from exc
