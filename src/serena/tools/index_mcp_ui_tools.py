"""Small UI/navigation tools backed by JetBrains Index MCP."""

from serena.index_mcp_client import IndexMcpClient
from serena.tools.tools_base import Tool


class OpenFileTool(Tool):
    """Opens a project file in the JetBrains editor through Index MCP."""

    def apply(self, relative_path: str, line: int | None = None, column: int | None = None) -> str:
        """
        Open a file in the JetBrains IDE, optionally navigating to a specific position.

        Serena uses 0-based line/column coordinates. The underlying Index MCP ``ide_open_file``
        tool uses 1-based coordinates, so this wrapper converts them before calling Index MCP.

        :param relative_path: path to the file, relative to the active Serena project root
        :param line: optional 0-based line to navigate to
        :param column: optional 0-based column to navigate to; requires ``line``
        :return: Index MCP's open-file result
        """
        self.project.validate_relative_path(relative_path)

        if line is not None and line < 0:
            raise ValueError(f"line must be >= 0, got {line}")
        if column is not None and line is None:
            raise ValueError("column requires line to be specified")
        if column is not None and column < 0:
            raise ValueError(f"column must be >= 0, got {column}")

        arguments: dict[str, str | int] = {"file": relative_path}
        if line is not None:
            arguments["line"] = line + 1
        if column is not None:
            arguments["column"] = column + 1

        result = IndexMcpClient(self.get_project_root()).call_tool("ide_open_file", arguments)
        if isinstance(result, dict):
            return self._to_json(result)
        return result
