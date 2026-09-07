"""Small UI/navigation tools backed by JetBrains Index MCP."""

import os

from serena.index_mcp_client import IndexMcpClient
from serena.tools.tools_base import Tool, ToolMarkerOptional


class OpenFileTool(Tool, ToolMarkerOptional):
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


class OpenProjectTool(Tool, ToolMarkerOptional):
    """Opens another project in the JetBrains IDE through Index MCP without changing Serena's active project."""

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
        if not os.path.isabs(path):
            raise ValueError(f"path must be absolute, got {path}")
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


class SwitchProjectTool(Tool, ToolMarkerOptional):
    """Opens a project in JetBrains through Index MCP and then activates the same project in Serena."""

    # noinspection PyIncorrectDocstring
    # (session_id is injected via apply_ex)
    def apply(self, path: str, session_id: str, auto_link: bool = False, timeout_seconds: int = 600) -> str:
        """
        Switch both JetBrains and Serena to a project by absolute filesystem path.

        This is the preferred project-switching operation for the Serena Index plugins. It first calls
        ``ide_open_project`` using the currently active project as Index MCP context, waits for the target
        project to open/index, and only then activates that path in Serena.

        :param path: absolute filesystem path of the project directory to open and activate
        :param auto_link: whether to automatically link an unlinked Maven/Gradle build after opening
        :param timeout_seconds: maximum seconds to wait for opening and indexing; must be positive
        """
        if not os.path.isabs(path):
            raise ValueError(f"path must be absolute, got {path}")
        if timeout_seconds <= 0:
            raise ValueError(f"timeout_seconds must be > 0, got {timeout_seconds}")

        arguments: dict[str, str | int | bool] = {
            "path": path,
            "autoLink": auto_link,
            "timeoutSeconds": timeout_seconds,
        }
        open_result = IndexMcpClient(self.get_project_root()).call_tool("ide_open_project", arguments)

        self.agent.activate_project_from_path_or_name(path)
        activation_result = self.agent.get_project_activation_message(session_id)

        if isinstance(open_result, dict):
            open_text = self._to_json(open_result)
        else:
            open_text = open_result
        return f"JetBrains: {open_text}\n\nSerena:\n{activation_result}"
