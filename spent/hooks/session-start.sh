#!/usr/bin/env bash
# spent -- SessionStart hook for Claude Code.

SPENT_DIR="$HOME/.spent"
LOG_FILE="$SPENT_DIR/claude-sessions.jsonl"
ENABLED_FLAG="$SPENT_DIR/tracking_enabled"
mkdir -p "$SPENT_DIR" 2>/dev/null || true

[ -f "$ENABLED_FLAG" ] && [ "$(cat "$ENABLED_FLAG" 2>/dev/null)" = "0" ] && exit 0

# Read payload -- SessionStart provides session_id
PAYLOAD=$(cat 2>/dev/null) || true

PY=""
if python3 -c "pass" >/dev/null 2>&1; then PY="python3"
elif python -c "pass" >/dev/null 2>&1; then PY="python"
fi

if [ -n "$PY" ]; then
    printf '%s' "$PAYLOAD" | $PY -c "
import sys, json
from datetime import datetime, timezone
try:
    d = json.loads(sys.stdin.read()) if sys.stdin.readable() else {}
except Exception:
    d = {}
session = d.get('session_id', 'unknown')[:16]
ts = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S')
record = json.dumps({'ts': ts, 'event': 'session_start', 'session': session})
with open('$HOME/.spent/claude-sessions.jsonl', 'a') as f:
    f.write(record + '\n')
" 2>/dev/null
else
    TS=$(date -u +"%Y-%m-%dT%H:%M:%S" 2>/dev/null || date +"%Y-%m-%dT%H:%M:%S")
    echo "{\"ts\":\"${TS}\",\"event\":\"session_start\",\"session\":\"unknown\"}" >> "$LOG_FILE" 2>/dev/null
fi

exit 0
