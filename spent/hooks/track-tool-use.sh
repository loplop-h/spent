#!/usr/bin/env bash
# spent -- PostToolUse hook for Claude Code session tracking.
# Receives REAL Claude Code hook payload via stdin with:
#   session_id, tool_name, tool_input, tool_response, cwd
# Appends one JSONL line to ~/.spent/claude-sessions.jsonl

SPENT_DIR="$HOME/.spent"
LOG_FILE="$SPENT_DIR/claude-sessions.jsonl"
ENABLED_FLAG="$SPENT_DIR/tracking_enabled"
mkdir -p "$SPENT_DIR" 2>/dev/null || true

# Check if tracking is disabled
[ -f "$ENABLED_FLAG" ] && [ "$(cat "$ENABLED_FLAG" 2>/dev/null)" = "0" ] && exit 0

# Read the hook payload from stdin
PAYLOAD=$(cat 2>/dev/null) || true
[ -z "$PAYLOAD" ] && exit 0

# Find working Python
PY=""
if python3 -c "pass" >/dev/null 2>&1; then PY="python3"
elif python -c "pass" >/dev/null 2>&1; then PY="python"
fi

if [ -n "$PY" ]; then
    printf '%s' "$PAYLOAD" | $PY -c "
import sys, json, os

try:
    d = json.loads(sys.stdin.read())

    tool = d.get('tool_name', 'unknown')
    session = d.get('session_id', 'unknown')

    # Measure actual input/output sizes
    tool_input = d.get('tool_input', {})
    tool_response = d.get('tool_response', {})

    input_size = len(json.dumps(tool_input))

    # Extract output -- handle different tool response formats
    stdout = tool_response.get('stdout', '') if isinstance(tool_response, dict) else str(tool_response)
    stderr = tool_response.get('stderr', '') if isinstance(tool_response, dict) else ''
    output_size = len(str(stdout)) + len(str(stderr))

    # Build output text for error detection (first 300 chars)
    output_text = str(stdout)[:200]
    if stderr:
        output_text = str(stderr)[:200]

    # Detect errors
    has_error = False
    if isinstance(tool_response, dict):
        has_error = bool(stderr) or tool_response.get('interrupted', False)
    if not has_error and any(kw in output_text.lower() for kw in ['error', 'traceback', 'failed', 'exception', 'command not found']):
        has_error = True

    # Get file path if available (for duplicate read detection)
    file_path = ''
    if isinstance(tool_input, dict):
        file_path = tool_input.get('file_path', tool_input.get('path', tool_input.get('command', '')))

    # ISO timestamp
    from datetime import datetime, timezone
    ts = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S')

    # Read model from SessionStart-persisted file
    model = ''
    try:
        model_file = os.path.join(os.path.expanduser('~'), '.spent', 'models', session[:16] + '.txt')
        with open(model_file) as mf:
            model = mf.read().strip()
    except (OSError, FileNotFoundError):
        pass

    record = {
        'ts': ts,
        'event': 'tool_use',
        'session': session[:16],
        'tool': tool,
        'model': model,
        'input_size': input_size,
        'output_size': output_size,
        'has_error': has_error,
        'file_path': str(file_path)[:200],
        'output_text': output_text.replace('\"', \"'\").replace('\n', ' ')[:200],
    }

    line = json.dumps(record, ensure_ascii=False)

    spent_dir = os.path.join(os.path.expanduser('~'), '.spent')
    os.makedirs(spent_dir, exist_ok=True)
    with open(os.path.join(spent_dir, 'claude-sessions.jsonl'), 'a') as f:
        f.write(line + '\n')

except Exception:
    pass
" 2>/dev/null
else
    # Fallback without Python -- minimal logging
    TS=$(date -u +'%Y-%m-%dT%H:%M:%S' 2>/dev/null || date +'%Y-%m-%dT%H:%M:%S')
    echo "{\"ts\":\"$TS\",\"event\":\"tool_use\",\"tool\":\"unknown\",\"input_size\":0,\"output_size\":0,\"session\":\"unknown\"}" >> "$LOG_FILE" 2>/dev/null
fi

exit 0
