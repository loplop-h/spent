#!/usr/bin/env bash
# spent -- Stop/SessionEnd hook for Claude Code.
# Records a session_end event and optionally prints a cost summary.

set -e

SPENT_DIR="$HOME/.spent"
LOG_FILE="$SPENT_DIR/claude-sessions.jsonl"

mkdir -p "$SPENT_DIR" 2>/dev/null || true

SESSION_ID="${CLAUDE_SESSION_ID:-$(date +%Y%m%d-%H%M)}"
MODEL="${CLAUDE_MODEL:-sonnet}"
TS=$(date -u +"%Y-%m-%dT%H:%M:%S" 2>/dev/null || date +"%Y-%m-%dT%H:%M:%S")

LINE="{\"ts\":\"${TS}\",\"session\":\"${SESSION_ID}\",\"model\":\"${MODEL}\",\"event\":\"session_end\"}"

echo "$LINE" >> "$LOG_FILE" 2>/dev/null || true

# Show final cost summary if spent CLI is available.
if command -v spent >/dev/null 2>&1; then
    spent status 2>/dev/null || true
fi

exit 0
