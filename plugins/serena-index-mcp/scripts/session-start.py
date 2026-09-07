#!/usr/bin/env python3
import json

message = (
    "Use JetBrains Index MCP `ide_*` tools as the primary code-intelligence/navigation layer. "
    "Prefer `ide_file_structure`, `ide_find_symbol`, `ide_find_definition`, `ide_find_references`, "
    "`ide_find_file`, and `ide_search_text` before raw Read/Glob/Grep on source code. "
    "Use the Serena fork for complementary project/editing workflows when Index MCP does not directly fit. "
    "Do not call Serena `initial_instructions` as a routine startup step; this plugin already provides the workflow guidance. "
    "The Index MCP HTTP endpoint is expected at http://127.0.0.1:29170/index-mcp/streamable-http."
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
