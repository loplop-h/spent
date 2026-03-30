#!/usr/bin/env bash
# spent -- Stop hook for Claude Code.
# Records a session_end event. Parses stdin for real session_id.

SPENT_DIR="$HOME/.spent"
LOG_FILE="$SPENT_DIR/claude-sessions.jsonl"
ENABLED_FLAG="$SPENT_DIR/tracking_enabled"
mkdir -p "$SPENT_DIR" 2>/dev/null || true

[ -f "$ENABLED_FLAG" ] && [ "$(cat "$ENABLED_FLAG" 2>/dev/null)" = "0" ] && exit 0

PAYLOAD=$(cat 2>/dev/null) || true

PY=""
if python3 -c "pass" >/dev/null 2>&1; then PY="python3"
elif python -c "pass" >/dev/null 2>&1; then PY="python"
fi

if [ -n "$PY" ]; then
    printf '%s' "$PAYLOAD" | $PY -c "
import sys, json
from datetime import datetime, timezone
from pathlib import Path

# Try to get session_id from the hook payload
session = ''
try:
    d = json.loads(sys.stdin.read())
    session = d.get('session_id', '')[:16]
except Exception:
    pass

# Fallback: read the last session_id from the log
if not session:
    log = Path.home() / '.spent' / 'claude-sessions.jsonl'
    if log.exists():
        for line in reversed(log.read_text().strip().split('\n')[-50:]):
            try:
                ev = json.loads(line)
                if ev.get('session'):
                    session = ev['session']
                    break
            except Exception:
                continue

ts = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S')
record = json.dumps({'ts': ts, 'event': 'session_end', 'session': session or 'unknown'})
with open(str(Path.home() / '.spent' / 'claude-sessions.jsonl'), 'a') as f:
    f.write(record + '\n')
" 2>/dev/null
else
    TS=\$(date -u +'%Y-%m-%dT%H:%M:%S' 2>/dev/null || date +'%Y-%m-%dT%H:%M:%S')
    echo \"{\\\"ts\\\":\\\"$TS\\\",\\\"event\\\":\\\"session_end\\\",\\\"session\\\":\\\"unknown\\\"}\" >> \"\$LOG_FILE\" 2>/dev/null
fi

# Show summary if CLI available
command -v spent >/dev/null 2>&1 && spent cc status 2>/dev/null || true

exit 0
