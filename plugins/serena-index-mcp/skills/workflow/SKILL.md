---
description: Use when working with the Areo-RGB Serena Index MCP fork, choosing between Serena and JetBrains Index MCP tools, explaining the integration, or troubleshooting its MCP/hook workflow.
---

# Serena Index MCP workflow

This plugin combines two layers:

1. **JetBrains Index MCP** is the primary code-intelligence/navigation layer.
2. **Areo-RGB/serena-main** is the complementary project/editing workflow layer and also delegates its patched search operations to Index MCP.

## Prefer Index MCP for discovery

Use the semantic/index-backed tool that matches the question before raw Read/Glob/Grep:

- file outline: `ide_file_structure`
- symbol lookup: `ide_find_symbol`
- exact declaration at a position: `ide_find_definition`
- references/usages: `ide_find_references`
- file-name search: `ide_find_file`
- text/regex search: `ide_search_text`
- signature/docs: `ide_symbol_info`
- implementations: `ide_find_implementations`
- caller/callee graph: `ide_call_hierarchy`
- inheritance graph: `ide_type_hierarchy`

Prefer Index MCP edit/refactor tools such as `ide_refactor_rename`, `ide_replace_text_in_file`, `ide_edit_member`, `ide_replace_member`, and `ide_insert_member` when enabled and applicable.

## Use Serena when it adds value

Use Serena for project activation, memories/project workflow, and edits/refactors that Index MCP cannot express cleanly. Avoid using Serena's old file/symbol-search path as the primary discovery layer; this fork is designed around Index MCP.

## Startup behavior

Do **not** call Serena `initial_instructions` as a routine Claude Code startup action. The plugin's SessionStart hook and this skill provide the workflow guidance without the extra large manual round trip.

## Runtime expectations

- Index MCP endpoint: `http://127.0.0.1:29170/index-mcp/streamable-http`
- Preferred local Serena checkout: `/home/paul/serena-main`
- Override the local checkout with `SERENA_FORK_HOME=/path/to/serena-main`.
- If no local virtualenv executable exists, the plugin falls back to `uvx --from git+https://github.com/Areo-RGB/serena-main.git`.

If Index MCP is unavailable, say so clearly and fall back to Serena or built-in tools rather than repeatedly retrying the same failed MCP call.
