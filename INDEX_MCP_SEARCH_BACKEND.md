# Serena Index MCP language backend

This fork integrates JetBrains Index MCP as a first-class Serena language backend instead of
embedding Index MCP calls in Serena's generic LSP tools.

Default Index MCP endpoint:

`http://127.0.0.1:29170/index-mcp/streamable-http`

## Architecture

```text
Agent
  |
  v
Serena MCP
  |
  +-- LanguageBackend.LSP -------> generic Serena / SolidLSP tools
  +-- LanguageBackend.JETBRAINS -> Serena JetBrains-plugin tools
  +-- LanguageBackend.INDEX_MCP -> dedicated IndexMcp* tools
                                      |
                                      v
                              JetBrains Index MCP
```

Start Serena with the Index MCP backend using:

```bash
serena start-mcp-server --language-backend IndexMCP
```

The Claude and VS Code plugins in this fork pass this option automatically.

## Current backend replacements

When `IndexMCP` is active, Serena's canonical tool roles are replaced by dedicated optional
backend implementations:

| Canonical Serena role | Effective IndexMCP Serena tool | Index MCP tool |
|---|---|---|
| `find_file` | `index_mcp_find_file` | `ide_find_file` |
| `get_symbols_overview` | `index_mcp_get_symbols_overview` | `ide_file_structure` |
| `find_symbol` | `index_mcp_find_symbol` | `ide_find_symbol` |
| `find_referencing_symbols` | `index_mcp_find_referencing_symbols` | `ide_find_references` |
| `search_for_pattern` | `index_mcp_search_for_pattern` | `ide_search_text` |

This mirrors Serena's upstream JetBrains backend design: generic LSP tools remain independent,
while backend-specific classes are selected through `LanguageBackend.get_lsp_tool_class_replacements()`
and an internal backend mode.

Serena preserves its own semantics at the adapter boundary, including 0-based positions, name-path
matching, path restrictions, glob filtering and result shaping. Index MCP positions are 1-based and
are converted to Serena's 0-based coordinate contract.

## Editing

The IndexMCP backend currently provides code intelligence through the five tools above. Generic
filesystem editing such as `replace_content` remains available through Serena's filesystem editor.
LSP-only symbolic edits/refactors are disabled in the IndexMCP internal mode until equivalent
Index MCP backend replacements are added.

## JetBrains setup

In **Settings > Tools > Index MCP Server**:

1. Keep the Streamable HTTP server running on port `29170`, or set `SERENA_INDEX_MCP_URL`.
2. Set **Response format** to **JSON**.
3. Enable the five required `ide_*` tools.
4. Keep the target project open/indexed. Serena supplies its active project root as `project_path`.

Optional environment overrides:

- `SERENA_INDEX_MCP_URL` — full Streamable HTTP endpoint.
- `SERENA_INDEX_MCP_TIMEOUT_SECONDS` — per-request timeout, default 30 seconds.

The Index adapter follows cursors and uses a defensive ceiling of 10,000 results for otherwise
unbounded searches.

## Client architecture

The Claude and VS Code plugins expose **only Serena** to the agent. There is no second direct
Index MCP connection in those plugins.

```text
Claude Code / VS Code
        |
        v
     Serena
        |
        v
   Index MCP
```
