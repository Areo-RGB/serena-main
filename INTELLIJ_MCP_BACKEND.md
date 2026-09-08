# Serena semantic reads backed by Code Intelligence MCP

This fork uses the small **Code Intelligence MCP (`intellij-mcp`)** JetBrains plugin as the semantic-read backend for Serena.

Default endpoint:

`http://127.0.0.1:9876/mcp`

## Tool mapping

| Serena tool | Code Intelligence MCP tool |
|---|---|
| `find_symbol` | `find_symbol` |
| `find_referencing_symbols` | `find_references` |
| `get_symbols_overview` | `get_file_symbols` |
| `get_symbol_info` | `get_symbol_info` |
| `get_type_hierarchy` | `get_type_hierarchy` |

The backend returns structured JSON and 1-based positions. Serena converts paths to project-relative paths and positions to its public 0-based convention.

## Deliberately not wrapped

The Code Intelligence MCP integration does not duplicate file-name search, text search, raw file reads, file/project opening, or shell operations. Claude Code and VS Code already provide those capabilities directly.

Serena's own LSP backend remains enabled for its native editing tools such as `replace_symbol_body`, `insert_before_symbol`, `insert_after_symbol`, `replace_content`, and `replace_in_files`.

## JetBrains setup

1. Install/start the Code Intelligence MCP (`intellij-mcp`) plugin.
2. Keep the target project open in JetBrains.
3. Ensure `http://127.0.0.1:9876/mcp` is reachable.
4. Wait for JetBrains indexing to finish before semantic queries that require PSI/index access.

Optional environment overrides:

- `SERENA_INTELLIJ_MCP_URL` — full MCP HTTP endpoint.
- `SERENA_INTELLIJ_MCP_TIMEOUT_SECONDS` — per-request timeout, default 30 seconds.

## Runtime architecture

```text
Claude Code / VS Code
        |
        v
     Serena
      /   \
     /     \
semantic   editing
 reads       |
   |         v
   v      Serena LSP
intellij-mcp
   |
   v
JetBrains PSI/index
```

The agent sees Serena only; intellij-mcp remains an internal backend.
