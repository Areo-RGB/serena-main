#!/usr/bin/env bash
set -euo pipefail

FORK_HOME="${SERENA_FORK_HOME:-/home/paul/serena-main}"
LOCAL_SERENA="$FORK_HOME/.venv/bin/serena"

if [[ -x "$LOCAL_SERENA" ]]; then
  exec "$LOCAL_SERENA" start-mcp-server --context=claude-code --project-from-cwd
fi

if ! command -v uvx >/dev/null 2>&1; then
  echo "serena-index-mcp: neither $LOCAL_SERENA nor uvx is available" >&2
  exit 127
fi

exec uvx \
  --from "git+https://github.com/Areo-RGB/serena-main.git" \
  serena start-mcp-server --context=claude-code --project-from-cwd
