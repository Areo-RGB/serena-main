---
description: Use when working with the Areo-RGB Serena fork backed by Code Intelligence MCP (intellij-mcp), choosing Serena tools, or troubleshooting the MCP/hook workflow.
---

# Serena + Code Intelligence MCP workflow

This plugin exposes **one MCP server to Claude Code: Serena** with a deliberately small tool surface.

Code Intelligence MCP (`intellij-mcp`) runs inside JetBrains and is used only as Serena's semantic-read backend. Do not look for or call it as a separate Claude-visible MCP server.

## Exposed Serena tools

Semantic reads:

- `get_symbols_overview` -> internal `get_file_symbols`
- `find_symbol` -> internal `find_symbol`
- `find_referencing_symbols` -> internal `find_references`
- `get_symbol_info` -> internal `get_symbol_info`
- `get_type_hierarchy` -> internal `get_type_hierarchy`
- `activate_project` -> Serena project selection

Editing through Serena/LSP:

- `replace_symbol_body`
- `insert_before_symbol`
- `insert_after_symbol`
- `replace_content`
- `replace_in_files`

Use Claude Code's native file-name search, text/regex search, file reads, navigation, and shell tools. Those operations are intentionally not duplicated in Serena.

## Runtime expectations

- Claude-visible MCP: Serena only.
- Serena is launched from `git+https://github.com/Areo-RGB/serena-main` through `uvx -p 3.13`.
- Serena is forced to `--language-backend LSP` for its native editing tools, so its separate `jet_brains_*` backend does not appear.
- Code Intelligence MCP is expected at `http://127.0.0.1:9876/mcp`.
- The corresponding Serena project must be open in JetBrains for semantic calls to resolve against the IDE project.
- Code Intelligence MCP uses 1-based positions; Serena exposes 0-based positions and converts at the adapter boundary.

If JetBrains reports that it is still indexing, wait for indexing to finish and retry the semantic read once. Do not treat normal dumb-mode/indexing state as a Serena adapter bug.

Do not call `initial_instructions` routinely. The Claude context and SessionStart hook already provide the workflow guidance.
