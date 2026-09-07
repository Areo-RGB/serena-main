# Serena Index MCP Claude Code plugin

This plugin exposes the Areo-RGB Serena fork as the single Claude Code MCP server. Selected Serena search/navigation tools use JetBrains Index MCP internally, but Claude does not connect to Index MCP directly.

## Install from GitHub

Add this repository as a Claude Code marketplace:

```text
/plugin marketplace add Areo-RGB/serena-main
```

Then install the plugin:

```text
/plugin install serena-index-mcp@areo-rgb
```

After installation, restart Claude Code or run `/reload-plugins` when prompted.

To refresh the marketplace later:

```bash
claude plugin marketplace update areo-rgb
```

## What it adds

- Serena fork MCP server (`serena-index`) as the only Claude-visible MCP
- Serena search/navigation wrappers backed internally by JetBrains Index MCP
- Concise SessionStart guidance that avoids the redundant `initial_instructions` startup round trip
- `/serena-index-mcp:workflow` skill explaining the single-MCP workflow and troubleshooting

## Existing Index-backed Serena wrappers

- `find_symbol` -> `ide_find_symbol`
- `get_symbols_overview` -> `ide_file_structure`
- `find_referencing_symbols` -> `ide_find_references`
- `find_file` -> `ide_find_file`
- `search_for_pattern` -> `ide_search_text`
- `open_file` -> `ide_open_file`

`open_file(relative_path, line?, column?)` opens the file in JetBrains. Serena accepts 0-based line/column values and converts them to the Index MCP tool's 1-based coordinates.

`ide_open_file` is disabled by default in Index MCP. Enable it in **Settings > Tools > Index MCP Server > Exposed Tools**.

Additional Index MCP capabilities can be wrapped by Serena later without adding a second Claude-visible MCP connection.

## Requirements

1. Claude Code
2. `uvx` / uv installed
3. JetBrains Index MCP running locally at:
   `http://127.0.0.1:29170/index-mcp/streamable-http`

The plugin runs Serena directly from this GitHub fork with Python 3.13 using the equivalent of:

```bash
uvx -p 3.13 --from git+https://github.com/Areo-RGB/serena-main serena start-mcp-server --context=claude-code --project-from-cwd
```

It does not require a local Serena checkout or virtualenv.

## Test locally

From the repository root:

```bash
claude --plugin-dir ./plugins/serena-index-mcp
```

Then run:

```text
/serena-index-mcp:workflow
```

Use `/plugin` to inspect plugin/MCP errors and `/reload-plugins` after changing plugin files.

## Tool strategy

Use Serena's Index-backed discovery/navigation wrappers first for source-code discovery and navigation. Use `open_file` when the user wants a source file opened in JetBrains. Use Serena's native symbolic/editing tools for functionality that has not yet been wrapped through Index MCP. Raw Read/Glob/Grep remain fallbacks.
