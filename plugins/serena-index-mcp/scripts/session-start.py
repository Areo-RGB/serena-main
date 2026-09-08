#!/usr/bin/env python3
import json

message = (
    "Use Serena as the single coding MCP. The exposed Serena toolset is intentionally lean. "
    "For semantic code reads prefer `get_symbols_overview`, `find_symbol`, `find_referencing_symbols`, "
    "`get_symbol_info`, and `get_type_hierarchy`; those five operations use Code Intelligence MCP "
    "(intellij-mcp) inside JetBrains. Use Claude Code's native file-name search, text search, reads, "
    "navigation, and shell tools instead of looking for Serena wrappers for those operations. "
    "Use Serena/LSP editing tools for edits. The Serena MCP is forced to the LSP backend, so do not "
    "look for or call separate `jet_brains_*` tools or a direct IntelliJ/Index MCP server. "
    "Do not call Serena `initial_instructions` routinely."
)

print(
    json.dumps(
        {
            "hookSpecificOutput": {
                "hookEventName": "SessionStart",
                "additionalContext": message,
            }
        }
    )
)
