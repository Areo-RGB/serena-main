#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "usage: run-hook.sh <activate|remind|auto-approve|reset|cleanup>" >&2
  exit 2
fi

HOOK_COMMAND="$1"
shift

if ! command -v uvx >/dev/null 2>&1; then
  echo "serena-index-mcp: uvx is required" >&2
  exit 127
fi

exec uvx \
  -p 3.13 \
  --from "git+https://github.com/Areo-RGB/serena-main" \
  serena-hooks "$HOOK_COMMAND" --client=claude-code "$@"
