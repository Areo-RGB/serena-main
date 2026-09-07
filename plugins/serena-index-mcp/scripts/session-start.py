#!/usr/bin/env python3
import json

message = (
    "Use the Serena MCP as the single coding MCP for this plugin. "
    "The exposed Serena toolset is intentionally lean. For discovery/navigation prefer "
    "`get_symbols_overview`, `find_symbol`, `find_referencing_symbols`, `find_file`, `search_for_pattern`, "
    "`open_file`, and `switch_project`; the discovery/navigation operations route through JetBrains Index MCP internally. "
    "Use `activate_project` only when Serena has no active project. "
    "The Serena MCP is forced to the LSP backend, so do not look for or call separate `jet_brains_*` tools. "
    "Do not call a separate direct `ide_*` MCP server and do not call Serena `initial_instructions` routinely."
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
