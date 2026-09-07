# Serena Index MCP Claude Code plugin

This plugin exposes the Areo-RGB Serena fork as the single Claude Code MCP server. Selected Serena discovery/navigation tools use JetBrains Index MCP internally, but Claude does not connect to Index MCP directly.

## Install from GitHub

```text
/plugin marketplace add Areo-RGB/serena-main
/plugin install serena-index-mcp@areo-rgb
```

After installation, restart Claude Code or run `/reload-plugins` when prompted.

To refresh later:

```bash
claude plugin marketplace update areo-rgb
claude plugin update serena-index-mcp@areo-rgb --scope user
```

## Lean tool surface

The Claude context intentionally exposes only this small Serena set:

- `activate_project`
- `find_file`
- `get_symbols_overview`
- `find_symbol`
- `find_referencing_symbols`
- `search_for_pattern`
- `open_file`
- `switch_project`
- `replace_symbol_body`
- `insert_before_symbol`
- `insert_after_symbol`
- `replace_content`
- `replace_in_files`

Serena diagnostics/config helpers, memories, cross-project query helpers, raw file/shell tools already provided by Claude Code, and the separate Serena JetBrains-plugin `jet_brains_*` tool family are deliberately omitted.

## Architecture

```text
Claude Code
    |
    v
Serena MCP (`serena-index`)
    |
    +-- find_file --------------------> ide_find_file
    +-- get_symbols_overview ---------> ide_file_structure
    +-- find_symbol ------------------> ide_find_symbol
    +-- find_referencing_symbols -----> ide_find_references
    +-- search_for_pattern -----------> ide_search_text
    +-- open_file --------------------> ide_open_file
    +-- switch_project ---------------> ide_open_project + Serena activation
                                        |
                                        v
                              JetBrains Index MCP
```

There is no separate Claude-visible Index MCP server.

`open_file(relative_path, line?, column?)` accepts Serena's 0-based line/column coordinates and converts them to Index MCP's 1-based coordinates.

`switch_project(path, auto_link=false, timeout_seconds=600)` first opens/indexes an absolute project path in JetBrains through `ide_open_project`, then activates the same path in Serena. Use `activate_project` alone when Serena has no active project yet.

`ide_open_file` and `ide_open_project` are opt-in Index MCP tools. Enable them under **Settings > Tools > Index MCP Server > Exposed Tools**.

## Runtime

The plugin explicitly uses Serena's **LSP** backend for the remaining native Serena tools, preventing the separate Serena JetBrains-plugin backend from injecting its `jet_brains_*` tools:

```bash
uvx -p 3.13 \
  --from git+https://github.com/Areo-RGB/serena-main \
  serena start-mcp-server \
  --context=claude-code \
  --language-backend LSP \
  --project-from-cwd
```

The Index-backed wrappers expect:

```text
http://127.0.0.1:29170/index-mcp/streamable-http
```

## Test locally

```bash
claude --plugin-dir ./plugins/serena-index-mcp
```

Then use `/plugin` to inspect the MCP tool list. It should show the lean Serena surface above and no `jet_brains_*` tools.
