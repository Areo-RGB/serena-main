# Serena search tools backed by JetBrains Index MCP

This fork routes Serena's five primary file/symbol search tools through the JetBrains Index MCP Streamable HTTP endpoint instead of Serena's language-server/file-system search implementations.

Default endpoint:

`http://127.0.0.1:29170/index-mcp/streamable-http`

## Tool mapping

| Serena tool | Index MCP tool |
|---|---|
| `find_symbol` | `ide_find_symbol` |
| `get_symbols_overview` | `ide_file_structure` |
| `find_referencing_symbols` | `ide_find_references` |
| `find_file` | `ide_find_file` |
| `search_for_pattern` | `ide_search_text` |

Serena's public tool names and parameters stay intact. The adapter translates Index MCP's 1-based positions, pagination, fuzzy symbol/file results, and file-structure tree into Serena-compatible output where practical.

## JetBrains setup

In **Settings > Tools > Index MCP Server**:

1. Keep the Streamable HTTP server running on port `29170` (or override the URL as described below).
2. Set **Response format** to **JSON**. Serena needs structured JSON payloads for translation.
3. Under **Exposed Tools**, enable the five tools above. In the supplied Index MCP plugin source, `ide_find_symbol` and `ide_file_structure` are disabled by default, so they must be enabled explicitly.
4. Keep the target project open in the IDE. Serena sends its active project root as `project_path` on every Index MCP call.

## Optional overrides

- `SERENA_INDEX_MCP_URL` — override the full Streamable HTTP endpoint.
- `SERENA_INDEX_MCP_TIMEOUT_SECONDS` — per-request HTTP timeout (default: 30 seconds).

The adapter follows Index MCP cursors and caps an otherwise-unbounded search at 10,000 indexed results as a defensive ceiling.

## Index-MCP-native hooks and Claude instructions

This fork also rewrites Serena's coding-agent guidance around Index MCP directly:

- repeated raw `Grep`/code-file reads are redirected to `ide_*` tools;
- successful Index MCP calls reset the hook's grep/read drift counters;
- the session-start hook names Index MCP as the primary discovery/navigation layer;
- Claude Code's context and prompt mapping prefer `ide_file_structure`, `ide_find_symbol`,
  `ide_find_definition`, `ide_find_references`, `ide_find_file`, and `ide_search_text`;
- Serena remains available as a complementary editing/project-workflow layer.

Hook classification is based on the leaf tool name (`ide_*`), not on the MCP server alias. For
Claude Code, use the matcher `mcp__.*__ide_.*`; this works whether the Index MCP server is named
`index-mcp`, `intellij-index`, or another alias.

A ready-to-copy Claude Code hooks configuration using this checkout's intended path
(`/home/paul/serena-main`) is included as `CLAUDE_INDEX_MCP_HOOKS.json`.
