from pathlib import Path


def replace_between(text: str, start: str, end: str, replacement: str) -> str:
    start_index = text.find(start)
    if start_index < 0:
        raise RuntimeError(f"start marker not found: {start!r}")
    end_index = text.find(end, start_index)
    if end_index < 0:
        raise RuntimeError(f"end marker not found: {end!r}")
    return text[:start_index] + replacement + text[end_index:]


# ---------------------------------------------------------------------------
# hooks.py: reset/reminder logic must recognize the Serena semantic wrapper
# names that the clients actually see. There is no agent-visible ide_* layer.
# ---------------------------------------------------------------------------
hooks_path = Path("src/serena/hooks.py")
hooks = hooks_path.read_text()

hooks = replace_between(
    hooks,
    "#: Index MCP exposes code-intelligence/refactoring tools with an ``ide_`` prefix.\n",
    "class PreToolUseHook(Hook, ABC):\n",
    '''#: Serena exposes the Code Intelligence MCP backend through a small semantic read surface.\n#: Clients namespace MCP tools differently, so classification uses the leaf tool name rather\n#: than the configured Serena MCP server name.\ndef _tool_leaf_name(tool_name: str) -> str:\n    name = tool_name.lower().strip()\n    for separator in ("__", ".", "/"):\n        if separator in name:\n            name = name.rsplit(separator, 1)[-1]\n    return name\n\n\n_SEMANTIC_CODE_TOOL_NAMES: frozenset[str] = frozenset(\n    {\n        "get_symbols_overview",\n        "find_symbol",\n        "find_referencing_symbols",\n        "get_symbol_info",\n        "get_type_hierarchy",\n    }\n)\n\n\ndef _is_semantic_code_tool_name(tool_name: str) -> bool:\n    return _tool_leaf_name(tool_name) in _SEMANTIC_CODE_TOOL_NAMES\n\n\n''',
)

hooks = hooks.replace(
    '''    def is_index_mcp_tool(self) -> bool:\n        return _is_index_mcp_tool_name(self._tool_name)\n''',
    '''    def is_semantic_code_tool(self) -> bool:\n        return _is_semantic_code_tool_name(self._tool_name)\n''',
)
hooks = hooks.replace("is_index_mcp_tool", "is_semantic_code_tool")
hooks = hooks.replace("_is_index_mcp_tool_name", "_is_semantic_code_tool_name")

hooks = replace_between(
    hooks,
    'class PreToolUseRemindAboutSymbolicToolsHook(PreToolUseHook):\n',
    '    @dataclass\n',
    '''class PreToolUseRemindAboutSymbolicToolsHook(PreToolUseHook):\n    """Nudge the agent toward Serena semantic code tools after repeated raw grep/read calls.\n\n    The persisted counters are reset whenever one of Serena's five semantic Code Intelligence MCP\n    wrappers is used, when a deny/reminder is emitted, or after the existing reset interval. Raw\n    file and text tools remain valid fallbacks for non-code, generated, malformed, or genuinely\n    text-oriented work.\n    """\n\n''',
)

hooks = hooks.replace(
    "# :meth:`reset` so the rate limit survives counter resets (e.g. Index MCP tool use)",
    "# :meth:`reset` so the rate limit survives counter resets (e.g. semantic Serena tool use)",
)
hooks = hooks.replace(
    "#: Index MCP's ``ide_search_text`` and structural navigation tools are the preferred\n    #: alternatives to repeated raw reads for source-like files.\n",
    "#: Serena's semantic Code Intelligence MCP wrappers are preferred over repeated raw reads\n    #: when the task is symbol- or structure-oriented.\n",
)

hooks = replace_between(
    hooks,
    '    def _build_grep_deny(self) -> "PreToolUseHook.OutputData":\n',
    '\n\nclass PostToolUseResetSymbolicToolCounterHook(Hook):\n',
    '''    def _build_grep_deny(self) -> "PreToolUseHook.OutputData":\n        return self.OutputData(\n            permission_decision="deny",\n            permission_decision_reason="Too many consecutive grep calls without using Serena semantic code tools. "\n            "You can continue using grep now if needed; the counter was reset.",\n            additional_context=(\n                "You were using many grep calls recently. For source-code discovery prefer Serena's semantic tools: "\n                "`find_symbol` for definitions, `find_referencing_symbols` for usages, "\n                "`get_symbols_overview` for file structure, `get_symbol_info` for signature/docs, and "\n                "`get_type_hierarchy` for inheritance. Use the client's normal file/text search when the query is "\n                "not semantic."\n            ),\n        )\n\n    def _build_code_read_deny(self) -> "PreToolUseHook.OutputData":\n        return self.OutputData(\n            permission_decision="deny",\n            permission_decision_reason="Too many consecutive code-file reads without using Serena semantic code tools. "\n            "You can continue using read now if needed; the counter was reset.",\n            additional_context=(\n                "You were repeatedly reading code files. Prefer `get_symbols_overview` to inspect structure, "\n                "`find_symbol` to locate a definition, `get_symbol_info` for type/signature/documentation, "\n                "`find_referencing_symbols` for usages, and `get_type_hierarchy` for inheritance before reading "\n                "larger source regions."\n            ),\n        )\n\n    def _build_non_symbolic_deny(self) -> "PreToolUseHook.OutputData":\n        return self.OutputData(\n            permission_decision="deny",\n            permission_decision_reason="Too many consecutive raw grep/read calls without using Serena semantic code tools. "\n            "You can continue using them now if needed; the counter was reset.",\n            additional_context=(\n                "You were alternating between grep and file reads. Switch to Serena's semantic code tools when the "\n                "question is about symbols, usages, signatures, file structure, or type inheritance; otherwise keep "\n                "using the client's built-in text/file tools."\n            ),\n        )\n''',
)

hooks = replace_between(
    hooks,
    'class PostToolUseResetSymbolicToolCounterHook(Hook):\n',
    '    def __init__(self, client: HookClient):\n',
    '''class PostToolUseResetSymbolicToolCounterHook(Hook):\n    """Reset raw grep/read drift counters after a successful Serena semantic tool call."""\n\n''',
)

hooks = replace_between(
    hooks,
    'class SessionStartActivateProjectHook(Hook):\n',
    '\n\nclass SessionEndCleanupHook(Hook):\n',
    '''class SessionStartActivateProjectHook(Hook):\n    def execute(self) -> None:\n        message = (\n            "**IMPORTANT**: For coding work, use Serena as the single MCP. Prefer `get_symbols_overview`, "\n            "`find_symbol`, `find_referencing_symbols`, `get_symbol_info`, and `get_type_hierarchy` for semantic "\n            "code understanding; those tools use Code Intelligence MCP internally. Use the client's native file/text "\n            "search for filenames and regex/text queries, and Serena's editing tools for changes. Activate the current "\n            "project in Serena before project-scoped work when no project is active."\n        )\n        result = {\n            "hookSpecificOutput": {\n                "hookEventName": "SessionStart",\n                "additionalContext": message,\n            }\n        }\n        click.echo(json.dumps(result))\n''',
)

hooks = hooks.replace("class PreToolUseAutoApproveIndexMcpHook", "class PreToolUseAutoApproveSemanticToolHook")
hooks = replace_between(
    hooks,
    'class PreToolUseAutoApproveSemanticToolHook(PreToolUseHook):\n',
    '    #: permission modes for which this hook emits an ``allow`` decision.',
    '''class PreToolUseAutoApproveSemanticToolHook(PreToolUseHook):\n    """Auto-approve Serena's read-only semantic code tools in permissive client modes.\n\n    These five tools only query Code Intelligence MCP; editing remains on Serena's separate edit tools and\n    therefore keeps the client's normal approval behavior.\n    """\n\n''',
)
hooks = hooks.replace(
    'permission_decision_reason=f"Auto-approved: Index MCP tool call while client is in {self._permission_mode} mode.",',
    'permission_decision_reason=f"Auto-approved: Serena semantic read while client is in {self._permission_mode} mode.",',
)
hooks = hooks.replace("PreToolUseAutoApproveIndexMcpHook(HookClient(client)).execute()", "PreToolUseAutoApproveSemanticToolHook(HookClient(client)).execute()")

hooks = hooks.replace(
    'help="Commands that steer coding agents toward Index MCP code intelligence and Serena editing workflows.",',
    'help="Commands that steer coding agents toward Serena semantic code tools and editing workflows.",',
)
hooks = hooks.replace(
    'help="Set this as SessionStart hook to prioritize Index MCP code intelligence and initialize Serena when edits are needed",',
    'help="Set this as SessionStart hook to prioritize Serena semantic code tools and activate projects when needed",',
)
hooks = hooks.replace(
    'help="Set this as PreToolUse hook to prefer Index MCP ide_* tools over repeated raw read_file/grep calls",',
    'help="Set this as PreToolUse hook to prefer Serena semantic code tools over repeated raw read_file/grep calls",',
)
hooks = hooks.replace(
    'help="Set this as PreToolUse hook to auto-approve Index MCP ide_* calls while the client is in a "\n        "permissive permission mode (acceptEdits or auto, Claude Code).",',
    'help="Set this as PreToolUse hook to auto-approve Serena semantic read calls while the client is in a "\n        "permissive permission mode (acceptEdits or auto, Claude Code).",',
)
hooks = hooks.replace(
    'help="Set this as PostToolUse hook, matched to Index MCP ide_* tools, to reset grep/read-drift "\n        "counters after a successful Index MCP call. For clients whose PreToolUse wiring only observes shell tools; "\n        "complements `remind`\'s own reset branch.",',
    'help="Set this as PostToolUse hook, matched to Serena semantic tools, to reset grep/read-drift "\n        "counters after a successful semantic call; complements `remind` for clients whose PreToolUse wiring only "\n        "observes shell tools.",',
)

# The old backend must not survive as executable guidance or matching logic.
for forbidden in ("ide_find_symbol", "ide_file_structure", "ide_find_references", "ide_find_file", "ide_search_text", "ide_*", "Index MCP"):
    if forbidden in hooks:
        raise RuntimeError(f"stale hook guidance remains: {forbidden}")
hooks_path.write_text(hooks)


# ---------------------------------------------------------------------------
# Global prompt: Serena is the only agent-visible MCP. The five semantic reads
# are the primary code-intelligence layer; client-native text/file tools fill the
# gaps that the new backend intentionally does not implement.
# ---------------------------------------------------------------------------
prompt_path = Path("src/serena/resources/config/prompt_templates/system_prompt.yml")
prompt = prompt_path.read_text()

prompt = replace_between(
    prompt,
    "    Some tasks require understanding a large part of the codebase; others need only a few symbols or a\n",
    "    {% if 'read_memory' in available_tools -%}\n",
    '''    Some tasks require understanding a large part of the codebase; others need only a few symbols or a\n    single file. Avoid reading whole files unless necessary. When available, prefer Serena's semantic code tools\n    before broad raw reads:\n\n    - `get_symbols_overview` for a source-file outline.\n    - `find_symbol` for definitions by name.\n    - `find_referencing_symbols` for semantic usages.\n    - `get_symbol_info` for type information, signatures, and documentation.\n    - `get_type_hierarchy` for inheritance relationships.\n\n    In the Claude Code and VS Code contexts these five Serena tools use Code Intelligence MCP internally. The\n    backend intentionally does not provide filename or text/regex search, so use the client's native file/text\n    tools for those queries. Raw reads remain appropriate for non-code, generated, malformed, or genuinely\n    text-oriented work.\n    \n''',
)
prompt = prompt.replace(
    "    Serena tool line numbers are 0-based; Index MCP locations are 1-based unless a tool schema states otherwise.\n",
    "    Serena tool line numbers are 0-based; Code Intelligence MCP locations are normalized by Serena before being returned.\n",
)

prompt = replace_between(
    prompt,
    "    # Tool selection (read this before every tool call on a code file)\n",
    "    # Doing tasks\n",
    '''    # Tool selection (read this before every tool call on a code file)\n\n    Serena is the single coding MCP exposed by this setup. Prefer its five semantic read tools for indexed\n    source-code understanding; Code Intelligence MCP is an internal backend and is not called directly.\n\n    ## Mapping\n\n    Task                                    Primary tool\n    --------------------------------------  ----------------------------------------\n    See a code file's structure             get_symbols_overview\n    Find a symbol by name                   find_symbol\n    Find references / usages                find_referencing_symbols\n    Get type/signature/docs                 get_symbol_info\n    Type / inheritance hierarchy            get_type_hierarchy\n    Search for a file                       Claude Code built-in file search\n    Search code text / regex                Claude Code built-in Grep/search\n    Symbol-level edit                       Serena replace_symbol_body / insert_*\n    Targeted text edit                      Serena replace_content / replace_in_files\n\n    Use Serena's semantic tools before broad code-file reads when the task is about symbols, relationships,\n    structure, signatures, or types. Use built-in file/text search when that is the actual query; the backend\n    intentionally exposes only the five semantic features above.\n\n    ## Required workflow before editing code\n\n    1. Locate and understand the target with the relevant Serena semantic read tool.\n    2. Check `find_referencing_symbols` before changing a public or widely-used symbol when usages matter.\n    3. Apply the smallest suitable Serena symbolic or targeted text edit. Use raw built-in Edit when Serena's\n       editing surface does not fit the change cleanly.\n\n    ## Self-check\n\n    Before broad Read/Grep operations on source code, ask whether one of the five Serena semantic tools answers\n    the question more directly. Do not force a semantic tool onto filename or text/regex searches.\n\n''',
)

for forbidden in ("ide_find_symbol", "ide_file_structure", "ide_find_references", "ide_find_file", "ide_search_text", "Index MCP"):
    if forbidden in prompt:
        raise RuntimeError(f"stale system-prompt guidance remains: {forbidden}")
prompt_path.write_text(prompt)

print("final Code Intelligence MCP prompt/hook cleanup applied")
