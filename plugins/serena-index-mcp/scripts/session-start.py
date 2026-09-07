#!/usr/bin/env python3
import json

message = (
    "Use the Serena MCP as the single coding MCP for this plugin. "
    "For discovery, prefer Serena `get_symbols_overview`, `find_symbol`, `find_referencing_symbols`, "
    "`find_file`, and `search_for_pattern`; in this fork those tools route through JetBrains Index MCP internally. "
    "Use Serena's remaining symbolic/editing tools for operations that do not yet have Index MCP wrappers. "
    "Do not look for or call a separate direct `ide_*` MCP server, and do not call Serena `initial_instructions` "
    "as a routine startup step."
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
