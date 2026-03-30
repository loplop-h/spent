#!/usr/bin/env bash
# spent -- SessionStart hook for Claude Code.
# Records a session_start event to the JSONL log.

set -e

SPENT_DIR="$HOME/.spent"
LOG_FILE="$SPENT_DIR/claude-sessions.jsonl"

mkdir -p "$SPENT_DIR" 2>/dev/null || true

SESSION_ID="${CLAUDE_SESSION_ID:-$(date +%Y%m%d-%H%M)}"
MODEL="${CLAUDE_MODEL:-sonnet}"
TS=$(date -u +"%Y-%m-%dT%H:%M:%S" 2>/dev/null || date +"%Y-%m-%dT%H:%M:%S")

LINE="{\"ts\":\"${TS}\",\"session\":\"${SESSION_ID}\",\"model\":\"${MODEL}\",\"event\":\"session_start\"}"

echo "$LINE" >> "$LOG_FILE" 2>/dev/null || true

exit 0
