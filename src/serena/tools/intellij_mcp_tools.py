"""Direct Serena tools backed by Code Intelligence MCP (intellij-mcp)."""

from __future__ import annotations

from typing import Any

from serena.intellij_mcp_client import IntellijMcpClient
from serena.tools.tools_base import Tool, ToolMarkerOptional, ToolMarkerSymbolicRead


def _normalise_location(client: IntellijMcpClient, location: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(location, dict):
        return None
    line = int(location.get("line") or 1)
    column = int(location.get("column") or 1)
    end_line = int(location.get("endLine") or line)
    end_column = int(location.get("endColumn") or column)
    return {
        "relative_path": client.relative_file_path(str(location.get("filePath") or "")),
        "line": max(0, line - 1),
        "column": max(0, column - 1),
        "end_line": max(0, end_line - 1),
        "end_column": max(0, end_column - 1),
        "preview": location.get("preview"),
    }


def _normalise_symbol_info(client: IntellijMcpClient, symbol: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": symbol.get("name"),
        "kind": symbol.get("kind"),
        "language": symbol.get("language"),
        "qualified_name": symbol.get("qualifiedName"),
        "signature": symbol.get("signature"),
        "documentation": symbol.get("documentation"),
        "location": _normalise_location(client, symbol.get("location")),
        "name_location": _normalise_location(client, symbol.get("nameLocation")),
        "return_type": symbol.get("returnType"),
        "parameters": symbol.get("parameters"),
        "modifiers": symbol.get("modifiers"),
        "decorators": symbol.get("decorators"),
        "annotations": symbol.get("annotations"),
        "super_types": symbol.get("superTypes"),
    }


class GetSymbolInfoTool(Tool, ToolMarkerSymbolicRead, ToolMarkerOptional):
    """Gets type information, documentation, and signature for a symbol through Code Intelligence MCP."""

    def apply(self, relative_path: str, line: int, column: int) -> str:
        """
        Get detailed symbol information at a source position.

        Serena uses 0-based line/column coordinates; intellij-mcp uses 1-based coordinates.

        :param relative_path: source file relative to the active Serena project
        :param line: 0-based source line
        :param column: 0-based source column
        :return: structured symbol information with Serena-style 0-based locations
        """
        self.project.validate_relative_path(relative_path)
        if line < 0 or column < 0:
            raise ValueError("line and column must be >= 0")

        client = IntellijMcpClient(self.get_project_root())
        result = client.call_tool(
            "get_symbol_info",
            {
                "filePath": client.absolute_file_path(relative_path),
                "line": line + 1,
                "column": column + 1,
            },
        )
        if not isinstance(result, dict):
            raise ValueError("Code Intelligence MCP returned no symbol information")
        return self._to_json(_normalise_symbol_info(client, result))


class GetTypeHierarchyTool(Tool, ToolMarkerSymbolicRead, ToolMarkerOptional):
    """Gets base types and subtypes for a class/interface through Code Intelligence MCP."""

    def apply(self, type_name: str, language: str | None = None, include_libraries: bool = False) -> str:
        """
        Get the inheritance hierarchy of a type.

        :param type_name: type name or qualified type name
        :param language: optional language id when the name is ambiguous
        :param include_libraries: include dependency/library types when supported
        :return: base and derived types with Serena-style 0-based locations
        """
        if not type_name.strip():
            raise ValueError("type_name must not be empty")

        client = IntellijMcpClient(self.get_project_root())
        arguments: dict[str, Any] = {
            "typeName": type_name,
            "includeLibraries": include_libraries,
        }
        if language:
            arguments["language"] = language
        result = client.call_tool("get_type_hierarchy", arguments)
        if not isinstance(result, dict):
            raise ValueError("Code Intelligence MCP returned no type hierarchy")

        def normalise_ref(ref: dict[str, Any]) -> dict[str, Any]:
            return {
                "name": ref.get("name"),
                "qualified_name": ref.get("qualifiedName"),
                "location": _normalise_location(client, ref.get("location")),
            }

        out = {
            "type_name": result.get("typeName"),
            "qualified_name": result.get("qualifiedName"),
            "kind": result.get("kind"),
            "super_types": [normalise_ref(ref) for ref in result.get("superTypes", []) if isinstance(ref, dict)],
            "sub_types": [normalise_ref(ref) for ref in result.get("subTypes", []) if isinstance(ref, dict)],
        }
        return self._to_json(out)
