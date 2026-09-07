---
description: Use when working with the Areo-RGB Serena Index MCP fork, choosing Serena tools, explaining the integration, or troubleshooting its MCP/hook workflow.
---

# Serena Index MCP workflow

This plugin exposes **one MCP server to Claude Code: Serena**.

JetBrains Index MCP remains an internal backend used by selected Serena tools. Claude should not call a separate direct `ide_*` MCP server.

## Index-backed Serena discovery and navigation tools

Prefer these Serena tools before raw Read/Glob/Grep:

- file outline: `get_symbols_overview` -> internal `ide_file_structure`
- symbol lookup: `find_symbol` -> internal `ide_find_symbol`
- references/usages: `find_referencing_symbols` -> internal `ide_find_references`
- file-name search: `find_file` -> internal `ide_find_file`
- text/regex search: `search_for_pattern` -> internal `ide_search_text`
- open file in JetBrains: `open_file` -> internal `ide_open_file`
- open project in JetBrains: `open_project` -> internal `ide_open_project`

`open_file` accepts an active-project-relative path plus optional Serena-style 0-based `line` and `column` coordinates. The wrapper converts them to Index MCP's 1-based coordinates.

`open_project` accepts an absolute project path plus optional `auto_link` and `timeout_seconds`. It opens the project in JetBrains and waits for indexing, using the current Serena project as the Index MCP request context.

## Other Serena tools

Use Serena's native symbolic/editing tools such as `find_declaration`, `find_implementations`, `rename_symbol`, `replace_symbol_body`, `insert_before_symbol`, `insert_after_symbol`, and `replace_content` when appropriate.

More Index MCP capabilities can be wrapped by Serena later. Until then, do not assume direct tools such as `ide_call_hierarchy`, `ide_type_hierarchy`, or `ide_refactor_rename` are available to Claude.

## Startup behavior

Do **not** call Serena `initial_instructions` as a routine Claude Code startup action. The plugin's SessionStart hook and Claude context already provide the required workflow guidance.

## Runtime expectations

- Claude-visible MCP: Serena only.
- Serena is launched from `git+https://github.com/Areo-RGB/serena-main` through `uvx -p 3.13`.
- No local Serena checkout or virtualenv is required.
- Serena's Index-backed wrappers expect the JetBrains Index MCP HTTP endpoint at `http://127.0.0.1:29170/index-mcp/streamable-http`.
- `ide_open_file` and `ide_open_project` are opt-in/disabled-by-default Index MCP tools; enable them under **Settings > Tools > Index MCP Server > Exposed Tools** before using Serena `open_file` or `open_project`.
- `ide_open_project` requires at least one JetBrains project to already be open so Index MCP has a request context.

If the internal Index MCP backend is unavailable, say so clearly and use Serena-native or built-in fallbacks where possible rather than repeatedly retrying the same failed wrapper call.
