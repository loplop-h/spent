#!/usr/bin/env bash
# spent -- PostToolUse hook for Claude Code session tracking.
# Appends one JSONL line per tool invocation to ~/.spent/claude-sessions.jsonl.
# Designed to be FAST (<50ms). Exit silently on any error.

SPENT_DIR="$HOME/.spent"
LOG_FILE="$SPENT_DIR/claude-sessions.jsonl"
mkdir -p "$SPENT_DIR" 2>/dev/null || true

# Read payload from stdin (Claude Code pipes JSON here).
PAYLOAD=$(cat 2>/dev/null) || true
[ -z "$PAYLOAD" ] && exit 0

# Find a working Python (test it actually runs, not just exists).
PY=""
if python3 -c "pass" >/dev/null 2>&1; then
    PY="python3"
elif python -c "pass" >/dev/null 2>&1; then
    PY="python"
fi

TOOL_NAME=""
INPUT_SIZE=0
OUTPUT_SIZE=0

if [ -n "$PY" ]; then
    PARSED=$(printf '%s' "$PAYLOAD" | $PY -c "
import sys, json
try:
    d = json.loads(sys.stdin.read())
    t = d.get('tool_name', d.get('tool', 'unknown'))
    inp = len(json.dumps(d.get('tool_input', d.get('input', ''))))
    out = len(json.dumps(d.get('tool_output', d.get('output', ''))))
    out_text = str(d.get('tool_output', d.get('output', '')))[:200]
    print(f'{t}\t{inp}\t{out}\t{out_text}')
except Exception:
    print('unknown\t0\t0\t')
" 2>/dev/null) || true

    if [ -n "$PARSED" ]; then
        TOOL_NAME=$(echo "$PARSED" | cut -f1)
        INPUT_SIZE=$(echo "$PARSED" | cut -f2)
        OUTPUT_SIZE=$(echo "$PARSED" | cut -f3)
        OUTPUT_TEXT=$(echo "$PARSED" | cut -f4)
    fi
fi

# Fallback if Python parsing failed
if [ -z "$TOOL_NAME" ] || [ "$TOOL_NAME" = "unknown" ]; then
    TOOL_NAME=$(echo "$PAYLOAD" | sed -n 's/.*"tool_name"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' | head -1)
    [ -z "$TOOL_NAME" ] && TOOL_NAME="unknown"
    INPUT_SIZE=${#PAYLOAD}
    OUTPUT_SIZE=0
    OUTPUT_TEXT=""
fi

SESSION_ID="${CLAUDE_SESSION_ID:-$(date +%Y%m%d-%H%M)}"
MODEL="${CLAUDE_MODEL:-sonnet}"
TS=$(date -u +"%Y-%m-%dT%H:%M:%S" 2>/dev/null || date +"%Y-%m-%dT%H:%M:%S")

# Build JSONL line -- include output_text for error detection
if [ -n "$OUTPUT_TEXT" ]; then
    # Escape quotes in output_text for JSON
    SAFE_TEXT=$(echo "$OUTPUT_TEXT" | sed 's/"/\\"/g' | tr '\n' ' ' | head -c 200)
    LINE="{\"ts\":\"${TS}\",\"tool\":\"${TOOL_NAME}\",\"input_size\":${INPUT_SIZE:-0},\"output_size\":${OUTPUT_SIZE:-0},\"session\":\"${SESSION_ID}\",\"model\":\"${MODEL}\",\"event\":\"tool_use\",\"output_text\":\"${SAFE_TEXT}\"}"
else
    LINE="{\"ts\":\"${TS}\",\"tool\":\"${TOOL_NAME}\",\"input_size\":${INPUT_SIZE:-0},\"output_size\":${OUTPUT_SIZE:-0},\"session\":\"${SESSION_ID}\",\"model\":\"${MODEL}\",\"event\":\"tool_use\"}"
fi

echo "$LINE" >> "$LOG_FILE" 2>/dev/null || true
exit 0
