# Serena Index MCP Claude Code plugin

This plugin packages the Areo-RGB Serena fork together with the JetBrains Index MCP workflow for Claude Code.

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

Then use Claude Code's plugin manager to update/reinstall `serena-index-mcp` when a newer plugin version is published.

## What it adds

- Serena fork MCP server (`serena-index`)
- JetBrains Index MCP HTTP server (`index-mcp`)
- Index-MCP-first reminder/auto-approval/reset hooks
- Concise SessionStart guidance that avoids the redundant `initial_instructions` startup round trip
- `/serena-index-mcp:workflow` skill explaining tool selection and troubleshooting

## Requirements

1. Claude Code
2. JetBrains Index MCP running at:
   `http://127.0.0.1:29170/index-mcp/streamable-http`
3. Either:
   - local fork checkout at `/home/paul/serena-main` with `.venv/bin/serena`, or
   - `uvx` installed so the plugin can run the fork directly from GitHub

To use another local checkout:

```bash
export SERENA_FORK_HOME=/path/to/serena-main
```

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

Use Index MCP `ide_*` tools first for source-code discovery and navigation. Use Serena for complementary project/editing workflows or when Index MCP cannot express the operation. Raw Read/Glob/Grep should be fallbacks for unindexed/generated/malformed files or genuinely text-oriented work.

## Notes

The plugin connects to the Index MCP HTTP endpoint; it does not launch the JetBrains IDE/plugin process itself. The Serena launcher and hook launcher prefer the local checkout for speed and fall back to the GitHub fork through `uvx` for portability.
