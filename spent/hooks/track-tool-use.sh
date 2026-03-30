#!/usr/bin/env bash
# spent -- PostToolUse hook for Claude Code session tracking.
# Appends one JSONL line per tool invocation to ~/.spent/claude-sessions.jsonl.
# Designed to be FAST (<50ms): read stdin, extract fields, append, exit.
# If anything fails, exit silently -- never block Claude Code.

set -e

SPENT_DIR="$HOME/.spent"
LOG_FILE="$SPENT_DIR/claude-sessions.jsonl"

# Ensure log directory exists (fast no-op if it already does).
mkdir -p "$SPENT_DIR" 2>/dev/null || true

# Read the hook payload from stdin (Claude Code pipes JSON here).
PAYLOAD=""
if ! read -r -t 2 PAYLOAD; then
    # No stdin or read timed out -- nothing to log.
    exit 0
fi

# Bail out if payload is empty.
[ -z "$PAYLOAD" ] && exit 0

# Extract fields using lightweight string inspection.
# We avoid jq for speed -- parse with bash builtins or simple tools.
# The payload is a JSON object; we pull out what we need with grep/sed.

# Tool name: look for "tool_name" or "tool" key.
TOOL=""
if command -v python3 >/dev/null 2>&1; then
    # Fast Python one-liner (available on most systems with Claude Code).
    TOOL=$(python3 -c "
import sys, json
try:
    d = json.loads(sys.argv[1])
    t = d.get('tool_name', d.get('tool', ''))
    inp = len(json.dumps(d.get('tool_input', d.get('input', ''))))
    out = len(json.dumps(d.get('tool_output', d.get('output', ''))))
    print(f'{t}\t{inp}\t{out}')
except Exception:
    print('\t0\t0')
" "$PAYLOAD" 2>/dev/null) || true
fi

# Parse the tab-delimited output.
if [ -n "$TOOL" ]; then
    TOOL_NAME=$(echo "$TOOL" | cut -f1)
    INPUT_SIZE=$(echo "$TOOL" | cut -f2)
    OUTPUT_SIZE=$(echo "$TOOL" | cut -f3)
else
    # Fallback: rough extraction without Python.
    TOOL_NAME=$(echo "$PAYLOAD" | sed -n 's/.*"tool_name"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' | head -1)
    [ -z "$TOOL_NAME" ] && TOOL_NAME=$(echo "$PAYLOAD" | sed -n 's/.*"tool"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' | head -1)
    INPUT_SIZE=${#PAYLOAD}
    OUTPUT_SIZE=0
fi

# Session ID: prefer env var, fall back to date-based ID.
SESSION_ID="${CLAUDE_SESSION_ID:-$(date +%Y%m%d-%H%M)}"

# Model: prefer env var, default to sonnet.
MODEL="${CLAUDE_MODEL:-sonnet}"

# Timestamp in ISO 8601.
TS=$(date -u +"%Y-%m-%dT%H:%M:%S" 2>/dev/null || date +"%Y-%m-%dT%H:%M:%S")

# Append one JSONL line. Use a single atomic write to avoid corruption.
LINE="{\"ts\":\"${TS}\",\"tool\":\"${TOOL_NAME}\",\"input_size\":${INPUT_SIZE:-0},\"output_size\":${OUTPUT_SIZE:-0},\"session\":\"${SESSION_ID}\",\"model\":\"${MODEL}\",\"event\":\"tool_use\"}"

echo "$LINE" >> "$LOG_FILE" 2>/dev/null || true

exit 0
