import json
import os
import pickle
import shutil
import sys
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Literal, Self

import click

from serena.util.cli_util import AutoRegisteringGroup

# copied from serena_config.py, we don't want to import anything here to keep the hook commands fast
serena_home_dir = os.getenv("SERENA_HOME", "").strip() or str(Path.home() / ".serena")


class HookClient(Enum):
    """The client application that triggered the hook."""

    CLAUDE_CODE = "claude-code"
    CODEBUDDY = "codebuddy"
    VSCODE = "vscode"
    CODEX = "codex"
    GROK = "grok"


class Hook(ABC):
    def __init__(self, client: HookClient):
        raw = sys.stdin.read()
        input_data = json.loads(raw, strict=False)
        self._input_data = input_data
        self._client = client

        session_id = input_data.get("session_id") or input_data.get("sessionId")
        if not session_id:
            raise ValueError("Session ID is required in the hook input data")
        self._session_id = str(session_id)
        self.session_persistence_dir = os.path.join(serena_home_dir, "hook_data", self._session_id)
        # tool input has a timestamp but using now is enough
        self.triggered_at_timestamp = datetime.now()

    @abstractmethod
    def execute(self) -> None:
        pass


#: Serena exposes the Code Intelligence MCP backend through a small semantic read surface.
#: Clients namespace MCP tools differently, so classification uses the leaf tool name rather
#: than the configured Serena MCP server name.
def _tool_leaf_name(tool_name: str) -> str:
    name = tool_name.lower().strip()
    for separator in ("__", ".", "/"):
        if separator in name:
            name = name.rsplit(separator, 1)[-1]
    return name


_SEMANTIC_CODE_TOOL_NAMES: frozenset[str] = frozenset(
    {
        "get_symbols_overview",
        "find_symbol",
        "find_referencing_symbols",
        "get_symbol_info",
        "get_type_hierarchy",
    }
)


def _is_semantic_code_tool_name(tool_name: str) -> bool:
    return _tool_leaf_name(tool_name) in _SEMANTIC_CODE_TOOL_NAMES


class PreToolUseHook(Hook, ABC):
    def __init__(self, client: HookClient):
        super().__init__(client)
        _tool_name = self._input_data.get("tool_name") or self._input_data.get("toolName", "") or ""
        _tool_name = str(_tool_name).lower().strip()
        if not _tool_name:
            raise ValueError("Tool name is required in the hook input data")
        self._tool_name = _tool_name
        raw_tool_input = self._input_data.get("tool_input") or self._input_data.get("toolInput")
        # TODO: some agents, like copilot CLI, can send a string as value for raw_tool_input
        #  Example: "tool_input":"*** Begin Patch\n*** Add File: /Users/acbdef/.copilot/session-state/08a961db-02f0-4c7c-b783-1e9818290292/files/hook-tool-test-3.txt\n+third edit tool test\n*** End Patch\n"
        #  We currently don't parse such tool input and hence don't react to it in hooks
        self._tool_input: dict | None = raw_tool_input if isinstance(raw_tool_input, dict) else None

        # only relevant in claude code at the moment, (not all events include this field; default to empty string)
        raw_permission_mode = self._input_data.get("permission_mode") or self._input_data.get("permissionMode") or ""
        self._permission_mode = str(raw_permission_mode).strip()

    @dataclass
    class OutputData:
        permission_decision: Literal["deny", "allow"]
        permission_decision_reason: str
        additional_context: str = ""

        def to_json_string(self, client: HookClient) -> str:
            if client == HookClient.GROK:
                grok_output: dict[str, str] = {"decision": self.permission_decision}
                if self.permission_decision == "deny":
                    grok_output["reason"] = self.permission_decision_reason
                return json.dumps(grok_output)

            hook_output = {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": self.permission_decision,
                    "permissionDecisionReason": self.permission_decision_reason,
                }
            }
            if client != HookClient.CODEX:
                hook_output["hookSpecificOutput"]["additionalContext"] = self.additional_context
            return json.dumps(hook_output)

    def is_semantic_code_tool(self) -> bool:
        return _is_semantic_code_tool_name(self._tool_name)


class PreToolUseRemindAboutSymbolicToolsHook(PreToolUseHook):
    """Nudge the agent toward Serena semantic code tools after repeated raw grep/read calls.

    The persisted counters are reset whenever one of Serena's five semantic Code Intelligence MCP
    wrappers is used, when a deny/reminder is emitted, or after the existing reset interval. Raw
    file and text tools remain valid fallbacks for non-code, generated, malformed, or genuinely
    text-oriented work.
    """

    @dataclass
    class ToolUseCounter:
        _FILE_NAME = "tool_use_counter.pkl"
        _GREP_USES_THRESHOLD = 3
        _READ_FILE_USES_THRESHOLD = 3
        # threshold for the combined "non-symbolic" counter that catches mixed sequences of grep+read
        _NON_SYMBOLIC_USES_THRESHOLD = 4

        # The following periods are set to essentially infinity since we neglect the per-tool reset periods for them
        _READ_FILE_RESET_PERIOD_SECONDS = 1000
        _GREP_RESET_PERIOD_SECONDS = 1000
        # reset period for the combined counter
        _NON_SYMBOLIC_RESET_PERIOD_SECONDS = 2000

        # minimum seconds between two engagements of the hook after a deny; the entire
        # hook (counter updates included) is a no-op while this window is active, so a
        # single sustained burst triggers at most one nudge per window
        _MIN_DENY_INTERVAL_SECONDS = 120

        n_recent_read_file_uses: int = 0
        n_recent_grep_uses: int = 0
        n_recent_non_symbolic_uses: int = 0
        last_grep_use_timestamp: datetime | None = None
        last_read_file_use_timestamp: datetime | None = None
        last_non_symbolic_use_timestamp: datetime | None = None
        # timestamp of the most recently emitted deny; deliberately not cleared by
        # :meth:`reset` so the rate limit survives counter resets (e.g. semantic Serena tool use)
        last_deny_timestamp: datetime | None = None

        def too_many_recent_reads(self) -> bool:
            return self.n_recent_read_file_uses >= self._READ_FILE_USES_THRESHOLD

        def too_many_recent_greps(self) -> bool:
            return self.n_recent_grep_uses >= self._GREP_USES_THRESHOLD

        def too_many_recent_non_symbolic(self) -> bool:
            return self.n_recent_non_symbolic_uses >= self._NON_SYMBOLIC_USES_THRESHOLD

        def is_hook_active(self, now: datetime) -> bool:
            """:return: whether the hook should engage at all at ``now``. Returns
            ``False`` while we are still within :attr:`_MIN_DENY_INTERVAL_SECONDS`
            of the most recent emitted deny — in that case the entire hook is
            short-circuited (no counter updates, no deny). Returns ``True`` when
            no deny has been emitted yet in this session, or when the window has
            elapsed.
            """
            if self.last_deny_timestamp is None:
                return True
            return (now - self.last_deny_timestamp).total_seconds() >= self._MIN_DENY_INTERVAL_SECONDS

        @classmethod
        def _get_persistence_path(cls, hook: Hook) -> Path:
            return Path(hook.session_persistence_dir) / cls._FILE_NAME

        @classmethod
        def load(cls, hook: Hook) -> Self:
            path = cls._get_persistence_path(hook)
            try:
                with open(path, "rb") as f:
                    return pickle.load(f)
            except Exception:
                return cls()

        def save(self, hook: Hook) -> None:
            path = self._get_persistence_path(hook)
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                with open(path, "wb") as f:
                    pickle.dump(self, f)
            except Exception:
                pass

        def update(self, hook: "PreToolUseRemindAboutSymbolicToolsHook") -> None:
            if hook.is_semantic_code_tool():
                self.reset()
                return

            now = hook.triggered_at_timestamp
            is_grep = hook.is_grep_call()
            is_code_file_read = hook.is_read_code_file_call()

            # update grep counter
            if is_grep:
                grep_period = self._GREP_RESET_PERIOD_SECONDS
                if self.last_grep_use_timestamp is not None and (now - self.last_grep_use_timestamp).total_seconds() <= grep_period:
                    self.n_recent_grep_uses += 1
                else:
                    self.n_recent_grep_uses = 1
                self.last_grep_use_timestamp = now

            # update read file counter
            if is_code_file_read:
                read_period = self._READ_FILE_RESET_PERIOD_SECONDS
                if (
                    self.last_read_file_use_timestamp is not None
                    and (now - self.last_read_file_use_timestamp).total_seconds() <= read_period
                ):
                    self.n_recent_read_file_uses += 1
                else:
                    self.n_recent_read_file_uses = 1
                self.last_read_file_use_timestamp = now

            # update combined non-symbolic counter — catches mixed bursts (e.g.
            # alternating grep/read) that neither per-tool counter would trip
            if is_grep or is_code_file_read:
                combined_period = self._NON_SYMBOLIC_RESET_PERIOD_SECONDS
                if (
                    self.last_non_symbolic_use_timestamp is not None
                    and (now - self.last_non_symbolic_use_timestamp).total_seconds() <= combined_period
                ):
                    self.n_recent_non_symbolic_uses += 1
                else:
                    self.n_recent_non_symbolic_uses = 1
                self.last_non_symbolic_use_timestamp = now

        def reset(self) -> None:
            self.n_recent_read_file_uses = 0
            self.n_recent_grep_uses = 0
            self.n_recent_non_symbolic_uses = 0
            self.last_grep_use_timestamp = None
            self.last_read_file_use_timestamp = None
            self.last_non_symbolic_use_timestamp = None

    #: substrings that, combined with ``"file"`` in the tool name, identify a
    #: read-file tool for non-Claude-Code clients (whose tool names vary across
    #: editors/agents). Lowercase because :attr:`_tool_name` is lowercased on
    #: ingest. Conservative on purpose: only verbs that strongly imply *reading*
    #: a file, never *modifying* one — so ``view_file``/``open_file``/``show_file``
    #: are caught alongside ``read_file``, while ``write_file``/``edit_file`` are not.
    _READ_FILE_VERB_SUBSTRINGS: frozenset[str] = frozenset(("read", "view", "open", "show"))

    #: Shell commands that perform grep-like search; used to classify Codex/Grok
    #: shell-command tool calls whose ``cmd`` or ``command`` field starts with one of these.
    _GREP_SHELL_COMMANDS: frozenset[str] = frozenset(("grep", "rg", "ag", "ack", "fgrep", "egrep"))

    #: Shell commands that perform file-read operations; used to classify Codex/Grok
    #: shell-command tool calls whose ``cmd`` or ``command`` field starts with one of these.
    _READ_SHELL_COMMANDS: frozenset[str] = frozenset(("cat", "head", "tail", "sed", "less", "more", "bat", "get-content", "gc"))

    #: file suffixes for source-like files where symbolic tools are usually more
    #: appropriate than repeated raw reads. Lowercase and extension-only.
    #: Serena's semantic Code Intelligence MCP wrappers are preferred over repeated raw reads
    #: when the task is symbol- or structure-oriented.
    _CODE_FILE_EXTENSIONS: frozenset[str] = frozenset(
        (
            ".al",
            ".bash",
            ".c",
            ".clj",
            ".cljs",
            ".cpp",
            ".cs",
            ".css",
            ".dart",
            ".elm",
            ".ex",
            ".exs",
            ".fs",
            ".fsx",
            ".go",
            ".graphql",
            ".gql",
            ".groovy",
            ".h",
            ".hcl",
            ".hpp",
            ".hs",
            ".html",
            ".java",
            ".jl",
            ".js",
            ".json",
            ".jsonc",
            ".jsx",
            ".kt",
            ".kts",
            ".lean",
            ".lua",
            ".m",
            ".matlab",
            ".nf",
            ".php",
            ".proto",
            ".ps1",
            ".py",
            ".r",
            ".rb",
            ".rs",
            ".scala",
            ".sh",
            ".sol",
            ".sql",
            ".svelte",
            ".swift",
            ".tf",
            ".tfvars",
            ".toml",
            ".ts",
            ".tsx",
            ".vue",
            ".yaml",
            ".yml",
            ".zig",
        )
    )

    def __init__(self, client: HookClient):
        super().__init__(client)
        self._tool_call_counter = self.ToolUseCounter.load(self)

        # extract a shell ``cmd``/``command`` field (Codex/Grok shell-command-style payloads):
        # split into command name (basename, lowercased) and the remaining argument string
        # so both bare names (``rg``) and path-prefixed invocations (``/usr/bin/grep``) are
        # normalised the same way. Stays ``None`` when no shell command is present.
        self._command: str | None = None
        self._command_name: str | None = None
        self._command_args_str: str | None = None
        # extract a direct file-path field (Claude Code's ``Read``/``Edit``/``Write`` tool
        # payloads pass the target as ``file_path`` rather than via a shell command).
        self._file_path: str | None = None
        if self._tool_input is not None:
            self._command = str(self._tool_input.get("cmd", self._tool_input.get("command", ""))).strip()
            if self._command:
                cmd_split = self._command.split(maxsplit=1)
                if len(cmd_split) > 1:
                    self._command_args_str = cmd_split[1]
                self._command_name = os.path.basename(cmd_split[0]).lower()
            file_path = (
                self._tool_input.get("file_path")
                or self._tool_input.get("filePath")
                or self._tool_input.get("target_file")
                or self._tool_input.get("targetFile")
                or ""
            )
            self._file_path = str(file_path).strip() or None

    def is_grep_call(self) -> bool:
        if self._client in (HookClient.CLAUDE_CODE, HookClient.CODEBUDDY):
            return self._tool_name == "grep"
        if self._client == HookClient.GROK:
            return self._tool_name == "grep" or (self._is_shell_command_call() and self._command_name in self._GREP_SHELL_COMMANDS)
        if self._client == HookClient.CODEX and self._is_shell_command_call():
            return self._command_name in self._GREP_SHELL_COMMANDS
        # heuristic for other clients
        return "grep" in self._tool_name

    def is_read_call(self) -> bool:
        if self._client in (HookClient.CLAUDE_CODE, HookClient.CODEBUDDY):
            return self._tool_name == "read" or "read_file" in self._tool_name
        if self._client == HookClient.GROK:
            return self._tool_name == "read_file" or (self._is_shell_command_call() and self._command_name in self._READ_SHELL_COMMANDS)
        if self._client == HookClient.CODEX and self._is_shell_command_call():
            return self._command_name in self._READ_SHELL_COMMANDS
        # heuristic for other clients
        name = self._tool_name
        if "file" not in name:
            return False
        return any(verb in name for verb in self._READ_FILE_VERB_SUBSTRINGS)

    def _is_shell_command_call(self) -> bool:
        """:return: whether the hook payload represents a shell-command tool call."""
        return self._command_name is not None

    def is_read_file_call(self) -> bool:
        """:return: whether the tool call reads a file-like target."""
        return self.is_read_call()

    def is_read_code_file_call(self) -> bool:
        """:return: whether the tool call reads a source-like file target."""
        if not self.is_read_file_call():
            return False

        if self._file_path is not None:
            return self._is_code_file_path(self._file_path)

        if self._client in (HookClient.CODEX, HookClient.GROK) and self._command_args_str is not None:
            return any(self._is_code_file_path(argument) for argument in self._iter_shell_path_arguments())

        return True

    def _iter_shell_path_arguments(self) -> list[str]:
        """:return: path-like shell arguments with quoting and common options removed."""
        arguments: list[str] = []
        if self._command_args_str is None:
            return arguments

        for raw_argument in self._command_args_str.split():
            argument = raw_argument.strip().strip("'\"")
            if not argument or argument.startswith("-"):
                continue
            arguments.append(argument)

        return arguments

    @classmethod
    def _is_code_file_path(cls, file_path: str) -> bool:
        """:return: whether ``file_path`` has a source-like suffix."""
        cleaned_path = file_path.strip().strip("'\"")
        if not cleaned_path:
            return False
        return Path(cleaned_path).suffix.lower() in cls._CODE_FILE_EXTENSIONS

    def execute(self) -> None:
        # gate the entire hook on the rate-limit window: while we are within
        # _MIN_DENY_INTERVAL_SECONDS of the last emitted deny, no counter
        # updates and no deny detection happen at all. The pickle is left
        # untouched so state survives the gating window unchanged.
        if not self._tool_call_counter.is_hook_active(self.triggered_at_timestamp):
            return

        self._tool_call_counter.update(self)

        # pick the deny that matches the current call first, so the emitted message lines up
        # with the tool the agent just invoked; fall back to the other per-tool counter only
        # if the current call did not itself trip a threshold (e.g. stale state loaded from
        # pickle). The combined non-symbolic deny is checked last — it only fires when neither
        # per-tool counter tripped, which is exactly the mixed-burst case (alternating grep/read).
        too_many_greps = self._tool_call_counter.too_many_recent_greps()
        too_many_reads = self._tool_call_counter.too_many_recent_reads()
        too_many_non_symbolic = self._tool_call_counter.too_many_recent_non_symbolic()

        output_data: PreToolUseHook.OutputData | None = None
        if self.is_grep_call() and too_many_greps:
            output_data = self._build_grep_deny()
        elif self.is_read_code_file_call() and too_many_reads:
            output_data = self._build_code_read_deny()
        elif too_many_greps:
            output_data = self._build_grep_deny()
        elif too_many_reads:
            output_data = self._build_code_read_deny()
        elif too_many_non_symbolic:
            output_data = self._build_non_symbolic_deny()

        if output_data is not None:
            # reset burst counters so the next interval starts fresh, then record
            # the deny timestamp and emit. The is_hook_active() guard at the top
            # ensures we never reach this branch within the rate-limit window.
            self._tool_call_counter.reset()
            self._tool_call_counter.last_deny_timestamp = self.triggered_at_timestamp
            click.echo(output_data.to_json_string(self._client))
        self._tool_call_counter.save(self)

    def _build_grep_deny(self) -> "PreToolUseHook.OutputData":
        return self.OutputData(
            permission_decision="deny",
            permission_decision_reason="Too many consecutive grep calls without using Serena semantic code tools. "
            "You can continue using grep now if needed; the counter was reset.",
            additional_context=(
                "You were using many grep calls recently. For source-code discovery prefer Serena's semantic tools: "
                "`find_symbol` for definitions, `find_referencing_symbols` for usages, "
                "`get_symbols_overview` for file structure, `get_symbol_info` for signature/docs, and "
                "`get_type_hierarchy` for inheritance. Use the client's normal file/text search when the query is "
                "not semantic."
            ),
        )

    def _build_code_read_deny(self) -> "PreToolUseHook.OutputData":
        return self.OutputData(
            permission_decision="deny",
            permission_decision_reason="Too many consecutive code-file reads without using Serena semantic code tools. "
            "You can continue using read now if needed; the counter was reset.",
            additional_context=(
                "You were repeatedly reading code files. Prefer `get_symbols_overview` to inspect structure, "
                "`find_symbol` to locate a definition, `get_symbol_info` for type/signature/documentation, "
                "`find_referencing_symbols` for usages, and `get_type_hierarchy` for inheritance before reading "
                "larger source regions."
            ),
        )

    def _build_non_symbolic_deny(self) -> "PreToolUseHook.OutputData":
        return self.OutputData(
            permission_decision="deny",
            permission_decision_reason="Too many consecutive raw grep/read calls without using Serena semantic code tools. "
            "You can continue using them now if needed; the counter was reset.",
            additional_context=(
                "You were alternating between grep and file reads. Switch to Serena's semantic code tools when the "
                "question is about symbols, usages, signatures, file structure, or type inheritance; otherwise keep "
                "using the client's built-in text/file tools."
            ),
        )


class PostToolUseResetSymbolicToolCounterHook(Hook):
    """Reset raw grep/read drift counters after a successful Serena semantic tool call."""

    def __init__(self, client: HookClient):
        super().__init__(client)
        raw_tool_name = self._input_data.get("tool_name") or self._input_data.get("toolName", "") or ""
        tool_name = str(raw_tool_name).lower().strip()
        if not tool_name:
            raise ValueError("Tool name is required in the hook input data")
        self._tool_name = tool_name
        raw_tool_response = self._input_data.get("tool_response") or self._input_data.get("toolResponse")
        self._tool_response: dict | None = raw_tool_response if isinstance(raw_tool_response, dict) else None

    def _call_succeeded(self) -> bool:
        # no structured response to check: be conservative and treat it as not confirmed
        # successful, rather than resetting on data we can't actually read
        if self._tool_response is None:
            return False
        return self._tool_response.get("isError") is not True

    def execute(self) -> None:
        if not _is_semantic_code_tool_name(self._tool_name) or not self._call_succeeded():
            return
        counter = PreToolUseRemindAboutSymbolicToolsHook.ToolUseCounter.load(self)
        counter.reset()
        counter.save(self)


class SessionStartActivateProjectHook(Hook):
    def execute(self) -> None:
        message = (
            "**IMPORTANT**: For coding work, use Serena as the single MCP. Prefer `get_symbols_overview`, "
            "`find_symbol`, `find_referencing_symbols`, `get_symbol_info`, and `get_type_hierarchy` for semantic "
            "code understanding; those tools use Code Intelligence MCP internally. Use the client's native file/text "
            "search for filenames and regex/text queries, and Serena's editing tools for changes. Activate the current "
            "project in Serena before project-scoped work when no project is active."
        )
        result = {
            "hookSpecificOutput": {
                "hookEventName": "SessionStart",
                "additionalContext": message,
            }
        }
        click.echo(json.dumps(result))


class SessionEndCleanupHook(Hook):
    def execute(self) -> None:
        shutil.rmtree(self.session_persistence_dir, ignore_errors=True)


class PreToolUseAutoApproveSemanticToolHook(PreToolUseHook):
    """Auto-approve Serena's read-only semantic code tools in permissive client modes.

    These five tools only query Code Intelligence MCP; editing remains on Serena's separate edit tools and
    therefore keeps the client's normal approval behavior.
    """

    #: permission modes for which this hook emits an ``allow`` decision. Frozen so the
    #: set is immutable at the class level; matching is exact (case-sensitive) against
    #: the canonical mode strings emitted by Claude Code's hook payload.
    _AUTO_APPROVE_MODES: frozenset[str] = frozenset({"acceptEdits", "auto"})

    def is_auto_approve_mode(self) -> bool:
        return self._permission_mode in self._AUTO_APPROVE_MODES

    def execute(self) -> None:
        # only emit a decision when both the tool and the mode match; stay silent otherwise
        if not self.is_semantic_code_tool() or not self.is_auto_approve_mode():
            return

        # name the actual mode in the reason so logs/debug output are unambiguous
        # (the same hook handles multiple modes now)
        output_data = self.OutputData(
            permission_decision="allow",
            permission_decision_reason=f"Auto-approved: Serena semantic read while client is in {self._permission_mode} mode.",
        )
        click.echo(output_data.to_json_string(self._client))


_client_option = click.option(
    "--client",
    type=click.Choice([e.value for e in HookClient], case_sensitive=False),
    default=HookClient.CLAUDE_CODE.value,
    show_default=True,
    help="The client application that triggered the hook.",
)


class HookCommands(AutoRegisteringGroup):
    def __init__(self) -> None:
        super().__init__(
            name="serena-hook",
            help="Commands that steer coding agents toward Serena semantic code tools and editing workflows.",
        )

    @staticmethod
    @click.command(
        "activate",
        help="Set this as SessionStart hook to prioritize Serena semantic code tools and activate projects when needed",
    )
    @_client_option
    def activate(client: str) -> None:
        SessionStartActivateProjectHook(HookClient(client)).execute()

    @staticmethod
    @click.command("cleanup", help="Set this as hook at session end all hook data for the current session")
    @_client_option
    def cleanup(client: str) -> None:
        SessionEndCleanupHook(HookClient(client)).execute()

    @staticmethod
    @click.command(
        "remind",
        help="Set this as PreToolUse hook to prefer Serena semantic code tools over repeated raw read_file/grep calls",
    )
    @_client_option
    def remind(client: str) -> None:
        PreToolUseRemindAboutSymbolicToolsHook(HookClient(client)).execute()

    @staticmethod
    @click.command(
        "auto-approve",
        help="Set this as PreToolUse hook to auto-approve Serena semantic read calls while the client is in a "
        "permissive permission mode (acceptEdits or auto, Claude Code).",
    )
    @_client_option
    def auto_approve(client: str) -> None:
        PreToolUseAutoApproveSemanticToolHook(HookClient(client)).execute()

    @staticmethod
    @click.command(
        "reset",
        help="Set this as PostToolUse hook, matched to Serena semantic tools, to reset grep/read-drift "
        "counters after a successful semantic call; complements `remind` for clients whose PreToolUse wiring only "
        "observes shell tools.",
    )
    @_client_option
    def reset(client: str) -> None:
        PostToolUseResetSymbolicToolCounterHook(HookClient(client)).execute()


hook_commands = HookCommands()
