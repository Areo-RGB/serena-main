# Serena Code Intelligence MCP Claude Code plugin

Package/install name remains `serena-index-mcp` for update compatibility, but the runtime backend is now the much smaller **Code Intelligence MCP (`intellij-mcp`)** service rather than JetBrains Index MCP.

Claude sees only Serena. Serena uses five intellij-mcp semantic tools internally and keeps its native LSP editing layer.

## Install / update

```text
/plugin marketplace add Areo-RGB/serena-main
/plugin install serena-index-mcp@areo-rgb
```

Update later with:

```bash
claude plugin marketplace update areo-rgb
claude plugin update serena-index-mcp@areo-rgb --scope user
```

## Lean tool surface

The Claude context exposes only these 11 Serena tools:

- `activate_project`
- `get_symbols_overview`
- `find_symbol`
- `find_referencing_symbols`
- `get_symbol_info`
- `get_type_hierarchy`
- `replace_symbol_body`
- `insert_before_symbol`
- `insert_after_symbol`
- `replace_content`
- `replace_in_files`

Claude Code already provides file-name search, text/regex search, file reads, navigation, shell access, and line editing, so Serena no longer duplicates those operations in this plugin.

## Architecture

```text
Claude Code
    |
    v
Serena MCP (`serena-index`)
    |
    +-- get_symbols_overview ---------> get_file_symbols
    +-- find_symbol ------------------> find_symbol
    +-- find_referencing_symbols -----> find_references
    +-- get_symbol_info --------------> get_symbol_info
    +-- get_type_hierarchy -----------> get_type_hierarchy
                                        |
                                        v
                         Code Intelligence MCP
                         http://127.0.0.1:9876/mcp
                         (inside JetBrains)

Serena editing tools
    |
    v
Serena / LSP
```

There is no separate Claude-visible IntelliJ/Index MCP connection.

## Runtime

The plugin starts Serena with:

```bash
uvx -p 3.13 \
  --from git+https://github.com/Areo-RGB/serena-main \
  serena start-mcp-server \
  --context=claude-code \
  --language-backend LSP \
  --project-from-cwd
```

Requirements:

1. Claude Code
2. `uv` / `uvx`
3. JetBrains IDE with the Code Intelligence MCP (`intellij-mcp`) plugin running
4. Target project open in JetBrains
5. MCP endpoint available at `http://127.0.0.1:9876/mcp` (override with `SERENA_INTELLIJ_MCP_URL`)

Code Intelligence MCP reports source positions as 1-based; Serena converts them to its public 0-based coordinate model.

## Test locally

```bash
claude --plugin-dir ./plugins/serena-index-mcp
```

The Serena MCP tool list should contain the 11 tools above, no `jet_brains_*` tools, and no old Index-MCP navigation wrappers such as `open_file` or `switch_project`.
