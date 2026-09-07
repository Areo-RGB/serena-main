---
description: Use when working with the Areo-RGB Serena Index MCP fork, choosing Serena tools, explaining the integration, or troubleshooting its MCP/hook workflow.
---

# Serena Index MCP workflow

This plugin exposes **one MCP server to Claude Code: Serena** with a deliberately small tool surface.

JetBrains Index MCP is an internal backend used by selected Serena tools. Do not look for or call a separate direct `ide_*` MCP server.

## Exposed Serena tools

Discovery/navigation:

- `find_file` -> internal `ide_find_file`
- `get_symbols_overview` -> internal `ide_file_structure`
- `find_symbol` -> internal `ide_find_symbol`
- `find_referencing_symbols` -> internal `ide_find_references`
- `search_for_pattern` -> internal `ide_search_text`
- `open_file` -> internal `ide_open_file`
- `switch_project` -> internal `ide_open_project`, then Serena project activation
- `activate_project` -> Serena-only activation when no project is active yet

Editing:

- `replace_symbol_body`
- `insert_before_symbol`
- `insert_after_symbol`
- `replace_content`
- `replace_in_files`

Do not expect Serena config/diagnostic helpers, memories, cross-project query helpers, raw file/shell tools, or the separate `jet_brains_*` backend tools in this plugin.

## Project switching

Use `activate_project` when Serena has no active project yet.

Once a project is active, prefer `switch_project(path, auto_link=false, timeout_seconds=600)` to move to another project. It opens/indexes the absolute path in JetBrains first and then activates the same path in Serena.

`ide_open_project` requires at least one JetBrains project to already be open as the Index MCP request context.

## Runtime expectations

- Claude-visible MCP: Serena only.
- Serena is launched from `git+https://github.com/Areo-RGB/serena-main` through `uvx -p 3.13`.
- The plugin forces `--language-backend LSP`, so Serena's separate JetBrains-plugin backend does not inject `jet_brains_*` tools.
- Index-backed wrappers expect `http://127.0.0.1:29170/index-mcp/streamable-http`.
- `ide_open_file` and `ide_open_project` are opt-in Index MCP tools; enable them under **Settings > Tools > Index MCP Server > Exposed Tools**.

Do not call `initial_instructions` routinely. The Claude context and SessionStart hook already provide the workflow guidance.
