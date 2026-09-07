#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "usage: run-hook.sh <activate|remind|auto-approve|reset|cleanup>" >&2
  exit 2
fi

HOOK_COMMAND="$1"
shift

FORK_HOME="${SERENA_FORK_HOME:-/home/paul/serena-main}"
LOCAL_HOOKS="$FORK_HOME/.venv/bin/serena-hooks"

if [[ -x "$LOCAL_HOOKS" ]]; then
  exec "$LOCAL_HOOKS" "$HOOK_COMMAND" --client=claude-code "$@"
fi

if ! command -v uvx >/dev/null 2>&1; then
  echo "serena-index-mcp: neither $LOCAL_HOOKS nor uvx is available" >&2
  exit 127
fi

exec uvx \
  --from "git+https://github.com/Areo-RGB/serena-main.git" \
  serena-hooks "$HOOK_COMMAND" --client=claude-code "$@"
