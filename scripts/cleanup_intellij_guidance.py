from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def replace_between(text: str, start_marker: str, end_marker: str, replacement: str) -> str:
    start = text.index(start_marker)
    end = text.index(end_marker, start)
    return text[:start] + replacement + text[end:]


# ---- hooks.py -------------------------------------------------------------
hooks_path = ROOT / "src/serena/hooks.py"
hooks = hooks_path.read_text(encoding="utf-8")

classifier = '''#: Serena semantic reads that should reset raw grep/read drift counters.
#: Tool names may be client-namespaced, so classification uses the leaf name.
_SEMANTIC_SERENA_TOOL_NAMES: frozenset[str] = frozenset(
    {
        "get_symbols_overview",
        "find_symbol",
        "find_referencing_symbols",
        "get_symbol_info",
        "get_type_hierarchy",
    }
)


def _tool_leaf_name(tool_name: str) -> str:
    name = tool_name.lower().strip()
    for separator in ("__", ".", "/"):
        if separator in name:
            name = name.rsplit(separator, 1)[-1]
    return name


def _is_semantic_serena_tool_name(tool_name: str) -> bool:
    return _tool_leaf_name(tool_name) in _SEMANTIC_SERENA_TOOL_NAMES
'''
hooks = replace_between(hooks, "#: Index MCP exposes", "\n\nclass PreToolUseHook", classifier)

hooks = hooks.replace(
    "    def is_index_mcp_tool(self) -> bool:\n        return _is_index_mcp_tool_name(self._tool_name)\n",
    "    def is_semantic_serena_tool(self) -> bool:\n        return _is_semantic_serena_tool_name(self._tool_name)\n",
)
hooks = hooks.replace("hook.is_index_mcp_tool()", "hook.is_semantic_serena_tool()")
hooks = hooks.replace("_is_index_mcp_tool_name", "_is_semantic_serena_tool_name")

pre_class = hooks.index("class PreToolUseRemindAboutSymbolicToolsHook")
doc_start = hooks.index('    """', pre_class)
doc_end = hooks.index('    """', doc_start + 7) + 7
hooks = hooks[:doc_start] + '''    """Nudges repeated raw source-code exploration toward Serena's semantic read tools.

    Native grep/read operations remain valid for genuinely text-oriented work. The hook only
    intervenes after repeated code-file reads/searches and resets its counters whenever one of
    Serena's semantic read tools is used.
    """''' + hooks[doc_end:]

hooks = hooks.replace(
    '    #: file suffixes for source-like files where symbolic tools are usually more\n'
    '    #: appropriate than repeated raw reads. Lowercase and extension-only.\n'
    '    #: Index MCP\'s ``ide_search_text`` and structural navigation tools are the preferred\n'
    '    #: alternatives to repeated raw reads for source-like files.\n',
    '    #: File suffixes for source-like files where semantic Serena tools may be more\n'
    '    #: efficient than repeated raw reads. Lowercase and extension-only.\n',
)

new_denies = '''    def _build_grep_deny(self) -> "PreToolUseHook.OutputData":
        return self.OutputData(
            permission_decision="deny",
            permission_decision_reason="Too many consecutive grep calls while exploring source code. "
            "You can continue using grep now if the query is genuinely text-oriented; the counter was reset.",
            additional_context=(
                "For semantic discovery, prefer Serena `find_symbol` for definitions and "
                "`find_referencing_symbols` for usages. Use grep for raw text/regex queries that those tools cannot express."
            ),
        )

    def _build_code_read_deny(self) -> "PreToolUseHook.OutputData":
        return self.OutputData(
            permission_decision="deny",
            permission_decision_reason="Too many consecutive source-file reads without using Serena semantic tools. "
            "You can continue reading now if needed; the counter was reset.",
            additional_context=(
                "For targeted code understanding, prefer Serena `get_symbols_overview` for file structure, "
                "`find_symbol` for definitions, and `get_symbol_info` for type/signature/documentation."
            ),
        )

    def _build_non_symbolic_deny(self) -> "PreToolUseHook.OutputData":
        return self.OutputData(
            permission_decision="deny",
            permission_decision_reason="Too many consecutive raw grep/read calls while exploring source code. "
            "You can continue using them now if needed; the counter was reset.",
            additional_context=(
                "Switch to Serena semantic reads when the question is structural: `get_symbols_overview`, `find_symbol`, "
                "`find_referencing_symbols`, `get_symbol_info`, or `get_type_hierarchy`. "
                "Keep native grep/read for genuinely textual or unindexed content."
            ),
        )
'''
hooks = replace_between(
    hooks,
    "    def _build_grep_deny",
    "\n\nclass PostToolUseResetSymbolicToolCounterHook",
    new_denies,
)

post_class = hooks.index("class PostToolUseResetSymbolicToolCounterHook")
post_doc_start = hooks.index('    """', post_class)
post_doc_end = hooks.index('    """', post_doc_start + 7) + 7
hooks = hooks[:post_doc_start] + '''    """Resets raw grep/read drift counters after a successful Serena semantic-read call."""''' + hooks[post_doc_end:]

# Clean stale comments left in the counter implementation.
hooks = hooks.replace("Index MCP tool use", "Serena semantic tool use")
hooks = hooks.replace("Index MCP ``ide_*`` tool use", "Serena semantic tool use")
hooks = hooks.replace("Index MCP ``ide_*`` tool", "Serena semantic tool")
hooks = hooks.replace("Index MCP", "Serena semantic")
hooks = hooks.replace("``ide_*``", "semantic")

assert "ide_" not in hooks, "stale ide_* guidance remains in hooks.py"
assert "Index MCP" not in hooks, "stale Index MCP guidance remains in hooks.py"
hooks_path.write_text(hooks, encoding="utf-8")


# ---- system prompt --------------------------------------------------------
prompt_path = ROOT / "src/serena/resources/config/prompt_templates/system_prompt.yml"
prompt = prompt_path.read_text(encoding="utf-8")
prompt = prompt.replace(
    "    CRITICAL: Before starting to work on a coding task, call the `initial_instructions` tool to read the 'Serena Instructions Manual'.",
    "    Follow the active Serena context. If `initial_instructions` is exposed and equivalent workflow guidance has not already been supplied, call it once before coding.",
)

semantic_prelude = '''    Some tasks require understanding a large part of the codebase; others need only a few symbols or a
    single file. Avoid reading whole files unless necessary. For semantic source-code understanding,
    prefer the Serena semantic tools that are available in the active context:
    - `get_symbols_overview` for a source-file outline.
    - `find_symbol` for definitions by symbol/name path.
    - `find_referencing_symbols` for semantic usages.
    - `get_symbol_info` for type, signature, and documentation when available.
    - `get_type_hierarchy` for inheritance relationships when available.

    In the lean Claude/VS Code contexts of this fork, these semantic reads are backed internally by
    Code Intelligence MCP (`intellij-mcp`) in JetBrains. The backend is an implementation detail; call
    the Serena tools, not a separate direct MCP server. Use client-native file-name search, text/regex
    search, raw reads, and navigation when those operations are genuinely the right abstraction.

'''
prompt = replace_between(prompt, "    Some tasks require understanding", "    {% if 'read_memory'", semantic_prelude)
prompt = prompt.replace(
    "    Serena tool line numbers are 0-based; Index MCP locations are 1-based unless a tool schema states otherwise.\n",
    "    Serena tool line numbers are 0-based. Backend-specific coordinates are normalized before results are exposed.\n",
)

cc_prefix = '''  cc_system_prompt_override: |
    You are Claude Code, Anthropic's official CLI for Claude. You are an interactive
    software-engineering agent. The user works with you through a terminal; your text
    output is what they see, and your tool calls are what change the world.

    # Tool selection (read this before every tool call on source code)

    This Serena fork exposes a small semantic code-intelligence surface. Prefer Serena's semantic
    tools when the question is about code structure or relationships:

    Task                                    Serena tool
    --------------------------------------  ----------------------------------------
    See a code file's structure             get_symbols_overview
    Find a symbol by name                   find_symbol
    Find references / usages                find_referencing_symbols
    Get type / signature / docs             get_symbol_info
    Type inheritance hierarchy              get_type_hierarchy

    In the lean plugin contexts these reads use Code Intelligence MCP (`intellij-mcp`) inside JetBrains
    internally. Do not look for or call a separate direct IntelliJ/Index MCP server.

    Use Claude Code's built-in Read/Glob/Grep for file-name search, raw text/regex search, file content,
    and unindexed/generated/malformed content. Those operations are intentionally not duplicated by Serena.

    For code changes, prefer the Serena editing tools exposed by the active context when they fit the
    operation (`replace_symbol_body`, `insert_before_symbol`, `insert_after_symbol`, `replace_content`,
    `replace_in_files`). Use raw built-in Edit when the change is better expressed as a client-native edit.

    ## Required workflow before editing code

    1. Use Serena semantic reads to understand the target when semantic context is useful.
    2. Make the smallest appropriate edit with Serena or the client-native editor.
    3. Use native search/read tools freely for genuinely textual work; don't force a semantic tool onto a text query.

    # Doing tasks
'''
prompt = replace_between(prompt, "  cc_system_prompt_override: |", "    # Doing tasks\n", cc_prefix)

assert "ide_" not in prompt, "stale ide_* guidance remains in system prompt"
assert "Index MCP" not in prompt, "stale Index MCP guidance remains in system prompt"
prompt_path.write_text(prompt, encoding="utf-8")

print("Updated hooks and prompt guidance for Code Intelligence MCP")
