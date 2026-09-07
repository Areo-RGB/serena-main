#!/usr/bin/env python3
import json

message = (
    "Use the Serena MCP as the single coding MCP for this plugin. "
    "For discovery, prefer Serena `index_mcp_get_symbols_overview`, `index_mcp_find_symbol`, `index_mcp_find_referencing_symbols`, "
    "`index_mcp_find_file`, and `index_mcp_search_for_pattern`; in this fork those tools route through JetBrains Index MCP internally. "
    "Use Serena's filesystem/editing tools that remain available for operations that do not yet have Index MCP wrappers. "
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
