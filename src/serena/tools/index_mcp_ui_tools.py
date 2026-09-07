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


class OpenProjectTool(Tool):
    """Opens another project in the JetBrains IDE through Index MCP."""

    def apply(self, path: str, auto_link: bool = False, timeout_seconds: int = 600) -> str:
        """
        Open a project by absolute filesystem path and wait for JetBrains indexing.

        The underlying ``ide_open_project`` tool requires an already-open JetBrains project as
        the MCP request context. Serena's active project is supplied as that context automatically.

        :param path: absolute filesystem path of the project directory to open
        :param auto_link: whether to automatically link an unlinked Maven/Gradle build after opening
        :param timeout_seconds: maximum seconds to wait for opening and indexing; must be positive
        :return: Index MCP's open-project result
        """
        if timeout_seconds <= 0:
            raise ValueError(f"timeout_seconds must be > 0, got {timeout_seconds}")

        arguments: dict[str, str | int | bool] = {
            "path": path,
            "autoLink": auto_link,
            "timeoutSeconds": timeout_seconds,
        }
        result = IndexMcpClient(self.get_project_root()).call_tool("ide_open_project", arguments)
        if isinstance(result, dict):
            return self._to_json(result)
        return result
