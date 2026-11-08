#!/usr/bin/env bash
# PostToolUse hook: format and fix the Python file Claude just edited, with the
# project's locked ruff. Never blocks (always exits 0).
set -uo pipefail

command -v jq >/dev/null 2>&1 || exit 0
file=$(jq -r '.tool_input.file_path // empty')
[[ -n "$file" && -f "$file" ]] || exit 0

case "$file" in
  *.py)
    root="${CLAUDE_PROJECT_DIR:-.}"
    uv run --project "$root" --only-group dev --no-sync ruff format --quiet "$file" >/dev/null 2>&1
    uv run --project "$root" --only-group dev --no-sync ruff check --fix --quiet "$file" >/dev/null 2>&1
    ;;
esac
exit 0
