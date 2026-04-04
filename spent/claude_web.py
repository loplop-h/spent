"""Claude Code session dashboard -- screenshot-worthy cost & efficiency tracking.

Serves a single-page dashboard on http://localhost:5051 using only
Python's built-in http.server. Zero external dependencies.

Reads session data from ~/.spent/claude-sessions.jsonl and computes
efficiency metrics, cost breakdowns, and actionable insights.

Usage:
    spent claude              # start on default port 5051
    spent claude --port 8080  # custom port
    spent claude --no-open    # don't auto-open browser
"""

from __future__ import annotations

import json
import threading
import webbrowser
from collections import defaultdict
from datetime import datetime, timezone
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from typing import Any

DEFAULT_PORT = 5051
JSONL_PATH = Path.home() / ".spent" / "claude-sessions.jsonl"

# Cost estimation and classification delegated to cost_engine via ClaudeTracker.
# The constants below are kept ONLY as fallbacks for the self-contained
# HTML dashboard rendering (which duplicates some logic for offline use).
# The canonical source of truth is cost_engine.py.
from .cost_engine import (
    CHARS_PER_TOKEN,
    BASE_OVERHEAD_TOKENS,
    CONTEXT_GROWTH_PER_TURN,
    MODEL_PRICING,
    PRODUCTIVE_TOOLS,
    NEUTRAL_TOOLS,
)
SONNET_INPUT_PER_1M = MODEL_PRICING["sonnet"].input_per_million
SONNET_OUTPUT_PER_1M = MODEL_PRICING["sonnet"].output_per_million


# ---------------------------------------------------------------------------
# Data helpers
# ---------------------------------------------------------------------------

def _safe_json(obj: Any) -> str:
    return json.dumps(obj, default=str, ensure_ascii=False)


def _read_events() -> list[dict]:
    """Read all events from the JSONL file."""
    if not JSONL_PATH.exists():
        return []
    events: list[dict] = []
    try:
        with open(JSONL_PATH, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        events.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
    except OSError:
        return []
    return events


def _events_by_session(events: list[dict]) -> dict[str, list[dict]]:
    """Group events by session id."""
    grouped: dict[str, list[dict]] = defaultdict(list)
    for ev in events:
        sid = ev.get("session", "unknown")
        grouped[sid].append(ev)
    return dict(grouped)


def _estimate_cost(input_size: int, output_size: int, turn_index: int) -> float:
    """Estimate USD cost for a single tool use."""
    input_tokens = (input_size / CHARS_PER_TOKEN) + BASE_OVERHEAD_TOKENS + (CONTEXT_GROWTH_PER_TURN * turn_index)
    output_tokens = output_size / CHARS_PER_TOKEN
    input_cost = (input_tokens / 1_000_000) * SONNET_INPUT_PER_1M
    output_cost = (output_tokens / 1_000_000) * SONNET_OUTPUT_PER_1M
    return round(input_cost + output_cost, 6)


def _classify_event(ev: dict, prev_reads: dict[str, float]) -> str:
    """Classify a tool_use event as productive, neutral, or wasted."""
    tool = ev.get("tool", "")
    output_text = ev.get("output", "")
    target = ev.get("target", "")
    ts_str = ev.get("ts", "")

    # Bash: wasted if error, otherwise productive (matches cost_engine.py)
    if tool == "Bash":
        if isinstance(output_text, str) and ("error" in output_text or "Error" in output_text):
            return "wasted"
        return "productive"

    # Wasted: repeated Read of same target within 60s
    if tool == "Read" and target:
        try:
            current_ts = datetime.fromisoformat(ts_str)
            last_ts_val = prev_reads.get(target)
            if last_ts_val is not None:
                delta = (current_ts - datetime.fromisoformat(str(last_ts_val))).total_seconds()
                if abs(delta) < 60:
                    return "wasted"
            prev_reads[target] = ts_str
        except (ValueError, TypeError):
            prev_reads[target] = ts_str

    if tool in PRODUCTIVE_TOOLS:
        return "productive"
    if tool in NEUTRAL_TOOLS:
        return "neutral"

    return "neutral"


def _tool_icon(tool: str) -> str:
    """Return a unicode icon for a tool name."""
    icons = {
        "Edit": "\u270f",       # pencil
        "Write": "\u2712",      # black nib
        "Read": "\U0001F4D6",   # open book
        "Bash": "\u2318",       # terminal
        "Grep": "\U0001F50D",   # magnifying glass
        "Glob": "\U0001F4C2",   # open folder
        "Agent": "\U0001F916",  # robot
        "TaskCreate": "\U0001F4CB",  # clipboard
        "TaskUpdate": "\U0001F504",  # arrows
    }
    return icons.get(tool, "\u2022")


def _compute_session_data(session_events: list[dict]) -> dict:
    """Compute all metrics for a single session."""
    tool_events = [e for e in session_events if e.get("event") == "tool_use"]
    start_events = [e for e in session_events if e.get("event") == "session_start"]
    end_events = [e for e in session_events if e.get("event") == "session_end"]

    # Session timing
    start_ts = None
    end_ts = None
    if start_events:
        try:
            start_ts = datetime.fromisoformat(start_events[0]["ts"])
        except (ValueError, KeyError):
            pass
    if end_events:
        try:
            end_ts = datetime.fromisoformat(end_events[-1]["ts"])
        except (ValueError, KeyError):
            pass
    if start_ts is None and tool_events:
        try:
            start_ts = datetime.fromisoformat(tool_events[0]["ts"])
        except (ValueError, KeyError):
            pass
    if end_ts is None and tool_events:
        try:
            end_ts = datetime.fromisoformat(tool_events[-1]["ts"])
        except (ValueError, KeyError):
            pass

    duration_seconds = 0
    if start_ts and end_ts:
        duration_seconds = max(int((end_ts - start_ts).total_seconds()), 0)

    # Classify each tool event and compute costs
    prev_reads: dict[str, float] = {}
    timeline: list[dict] = []
    productive_cost = 0.0
    neutral_cost = 0.0
    wasted_cost = 0.0
    cost_by_tool: dict[str, float] = defaultdict(float)
    cost_over_time: list[dict] = []

    for i, ev in enumerate(tool_events):
        input_size = ev.get("input_size", 0)
        output_size = ev.get("output_size", 0)
        cost = _estimate_cost(input_size, output_size, i)
        classification = _classify_event(ev, prev_reads)

        if classification == "productive":
            productive_cost += cost
        elif classification == "wasted":
            wasted_cost += cost
        else:
            neutral_cost += cost

        tool = ev.get("tool", "Unknown")
        cost_by_tool[tool] += cost

        ts_str = ev.get("ts", "")
        description = ev.get("description", "")
        target = ev.get("target", "")
        if not description:
            if target:
                description = f"{tool}: {target}"
            else:
                description = f"{tool} invocation"

        timeline.append({
            "ts": ts_str,
            "tool": tool,
            "icon": _tool_icon(tool),
            "description": description,
            "classification": classification,
            "cost": round(cost, 6),
        })

        cost_over_time.append({
            "ts": ts_str,
            "productive": round(productive_cost, 6),
            "neutral": round(neutral_cost, 6),
            "wasted": round(wasted_cost, 6),
        })

    total_cost = productive_cost + neutral_cost + wasted_cost
    efficiency = 0
    if total_cost > 0:
        efficiency = round((productive_cost / total_cost) * 100)

    # Generate insights
    insights = _generate_insights(tool_events, timeline, cost_by_tool, total_cost)

    return {
        "duration_seconds": duration_seconds,
        "total_cost": round(total_cost, 6),
        "efficiency": efficiency,
        "productive_cost": round(productive_cost, 6),
        "neutral_cost": round(neutral_cost, 6),
        "wasted_cost": round(wasted_cost, 6),
        "productive_pct": round((productive_cost / total_cost * 100) if total_cost > 0 else 0),
        "neutral_pct": round((neutral_cost / total_cost * 100) if total_cost > 0 else 0),
        "wasted_pct": round((wasted_cost / total_cost * 100) if total_cost > 0 else 0),
        "cost_by_tool": dict(sorted(cost_by_tool.items(), key=lambda x: x[1], reverse=True)),
        "cost_over_time": cost_over_time,
        "timeline": list(reversed(timeline)),
        "insights": insights,
        "event_count": len(tool_events),
    }


def _generate_insights(
    tool_events: list[dict],
    timeline: list[dict],
    cost_by_tool: dict[str, float],
    total_cost: float,
) -> list[dict]:
    """Generate actionable tips based on session data."""
    insights: list[dict] = []

    # Repeated reads
    read_targets: dict[str, int] = defaultdict(int)
    for ev in tool_events:
        if ev.get("tool") == "Read" and ev.get("target"):
            read_targets[ev["target"]] += 1
    for target, count in sorted(read_targets.items(), key=lambda x: x[1], reverse=True):
        if count >= 3:
            insights.append({
                "type": "warning",
                "text": f"You read {target} {count} times. Consider keeping it open.",
            })
            if len(insights) >= 2:
                break

    # Failed bash commands
    failed_bash = [t for t in timeline if t["tool"] == "Bash" and t["classification"] == "wasted"]
    if len(failed_bash) >= 2:
        total_wasted_bash = sum(t["cost"] for t in failed_bash)
        insights.append({
            "type": "error",
            "text": f"{len(failed_bash)} Bash commands failed. Total wasted: ${total_wasted_bash:.4f}",
        })

    # Most expensive tool
    if cost_by_tool and total_cost > 0:
        top_tool = max(cost_by_tool, key=cost_by_tool.get)
        top_cost = cost_by_tool[top_tool]
        top_pct = round((top_cost / total_cost) * 100)
        insights.append({
            "type": "info",
            "text": f"Most expensive tool: {top_tool} (${top_cost:.4f}, {top_pct}%)",
        })

    # Wasted percentage
    wasted_items = [t for t in timeline if t["classification"] == "wasted"]
    if wasted_items:
        wasted_total = sum(t["cost"] for t in wasted_items)
        if total_cost > 0 and (wasted_total / total_cost) > 0.2:
            insights.append({
                "type": "warning",
                "text": "Over 20% of cost was wasted. Review failed commands and repeated reads.",
            })

    # Low productive percentage
    productive_items = [t for t in timeline if t["classification"] == "productive"]
    if timeline and not productive_items:
        insights.append({
            "type": "warning",
            "text": "No productive actions detected yet. Start editing or writing code!",
        })

    if not insights:
        insights.append({
            "type": "success",
            "text": "Great session! No major efficiency issues detected.",
        })

    return insights


def _get_latest_session(events: list[dict]) -> str | None:
    """Return the most recent session id."""
    for ev in reversed(events):
        if ev.get("session"):
            return ev["session"]
    return None


def _compute_history(events: list[dict]) -> list[dict]:
    """Compute summary stats for all past sessions."""
    grouped = _events_by_session(events)
    history: list[dict] = []
    for sid, session_events in grouped.items():
        data = _compute_session_data(session_events)
        start_events = [e for e in session_events if e.get("event") == "session_start"]
        started = start_events[0].get("ts", "") if start_events else ""
        history.append({
            "session": sid,
            "started": started,
            "efficiency": data["efficiency"],
            "total_cost": data["total_cost"],
            "event_count": data["event_count"],
            "duration_seconds": data["duration_seconds"],
        })
    history.sort(key=lambda x: x.get("started", ""), reverse=True)
    return history


def _fmt_duration(seconds: int) -> str:
    """Format duration as human-readable string."""
    if seconds < 60:
        return f"{seconds}s"
    minutes = seconds // 60
    secs = seconds % 60
    if minutes < 60:
        return f"{minutes}m {secs}s"
    hours = minutes // 60
    mins = minutes % 60
    return f"{hours}h {mins}m"


# ---------------------------------------------------------------------------
# HTTP Handler
# ---------------------------------------------------------------------------

class ClaudeDashboardHandler(BaseHTTPRequestHandler):
    """Handle dashboard HTTP requests."""

    storage_events: list[dict] = []

    def log_message(self, format: str, *args: Any) -> None:
        """Suppress default request logging."""
        pass

    def _send_json(self, data: Any, status: int = 200) -> None:
        body = _safe_json(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, html: str, status: int = 200) -> None:
        body = html.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        events = _read_events()

        if self.path == "/":
            self._send_html(DASHBOARD_HTML)
        elif self.path == "/api/session":
            latest_sid = _get_latest_session(events)
            if latest_sid is None:
                self._send_json({"error": "No sessions found", "data": None})
                return
            grouped = _events_by_session(events)
            session_events = grouped.get(latest_sid, [])
            data = _compute_session_data(session_events)
            data["session_id"] = latest_sid
            self._send_json(data)
        elif self.path == "/api/history":
            history = _compute_history(events)
            avg_eff = 0
            if history:
                avg_eff = round(sum(h["efficiency"] for h in history) / len(history))
            self._send_json({"sessions": history, "average_efficiency": avg_eff})
        elif self.path == "/api/share":
            latest_sid = _get_latest_session(events)
            if latest_sid is None:
                self._send_html("<p>No session data</p>")
                return
            grouped = _events_by_session(events)
            session_events = grouped.get(latest_sid, [])
            data = _compute_session_data(session_events)
            self._send_html(_share_card_html(data))
        else:
            self.send_response(404)
            self.end_headers()


def _share_card_html(data: dict) -> str:
    """Generate a self-contained HTML share card for screenshotting."""
    eff = data["efficiency"]
    if eff >= 80:
        ring_color = "#3fb950"
    elif eff >= 60:
        ring_color = "#d29922"
    elif eff >= 40:
        ring_color = "#d29922"
    else:
        ring_color = "#f85149"

    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{background:#0a0e14;display:flex;justify-content:center;align-items:center;min-height:100vh;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif}}
.card{{background:linear-gradient(135deg,#141922 0%,#1a2233 100%);border:1px solid #1e2733;border-radius:16px;padding:32px 40px;width:480px;text-align:center;box-shadow:0 8px 32px rgba(0,0,0,0.5)}}
.brand{{color:#8b949e;font-size:12px;letter-spacing:2px;text-transform:uppercase;margin-bottom:16px}}
.score-ring{{width:120px;height:120px;border-radius:50%;background:conic-gradient({ring_color} {eff * 3.6}deg, #1e2733 0deg);display:inline-flex;align-items:center;justify-content:center;margin:8px 0 16px}}
.score-inner{{width:96px;height:96px;border-radius:50%;background:#141922;display:flex;flex-direction:column;align-items:center;justify-content:center}}
.score-num{{color:#e6edf3;font-size:28px;font-weight:700;line-height:1}}
.score-label{{color:#8b949e;font-size:10px;margin-top:2px}}
.stats{{display:flex;gap:16px;justify-content:center;margin:16px 0}}
.stat{{flex:1}}
.stat-val{{color:#e6edf3;font-size:18px;font-weight:600}}
.stat-lbl{{color:#8b949e;font-size:11px}}
.bar{{display:flex;height:6px;border-radius:3px;overflow:hidden;margin:16px 0 8px}}
.bar-prod{{background:#3fb950}}
.bar-neut{{background:#8b949e}}
.bar-waste{{background:#f85149}}
.footer{{color:#484f58;font-size:11px;margin-top:12px}}
</style></head><body>
<div class="card">
<div class="brand">Claude Code Session</div>
<div class="score-ring"><div class="score-inner"><span class="score-num">{eff}%</span><span class="score-label">efficiency</span></div></div>
<div class="stats">
<div class="stat"><div class="stat-val">${data['total_cost']:.4f}</div><div class="stat-lbl">Total Cost</div></div>
<div class="stat"><div class="stat-val">{data['event_count']}</div><div class="stat-lbl">Actions</div></div>
<div class="stat"><div class="stat-val">{_fmt_duration(data['duration_seconds'])}</div><div class="stat-lbl">Duration</div></div>
</div>
<div class="bar">
<div class="bar-prod" style="width:{data['productive_pct']}%"></div>
<div class="bar-neut" style="width:{data['neutral_pct']}%"></div>
<div class="bar-waste" style="width:{data['wasted_pct']}%"></div>
</div>
<div class="footer">tracked by spent -- see what your AI really costs</div>
</div>
</body></html>"""


# ---------------------------------------------------------------------------
# Dashboard HTML
# ---------------------------------------------------------------------------

DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Claude Code Dashboard -- spent</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.7/dist/chart.umd.min.js"></script>
<style>
/* ------------------------------------------------------------------ reset */
*,*::before,*::after{margin:0;padding:0;box-sizing:border-box}
html{font-size:14px;-webkit-font-smoothing:antialiased}
body{
  background:#0a0e14;color:#e6edf3;
  font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,'Helvetica Neue',Arial,sans-serif;
  line-height:1.5;padding:24px;min-height:100vh;
}
a{color:#58a6ff;text-decoration:none}
a:hover{text-decoration:underline}

/* ----------------------------------------------------------- layout shell */
.dash{max-width:1200px;margin:0 auto}
.row{display:flex;gap:16px;margin-bottom:16px;flex-wrap:wrap}
.row > *{flex:1;min-width:0}

/* ------------------------------------------------------------------ cards */
.card{
  background:#141922;border:1px solid #1e2733;border-radius:12px;
  padding:20px;position:relative;overflow:hidden;
}
.card-header{
  display:flex;justify-content:space-between;align-items:center;
  margin-bottom:12px;
}
.card-title{color:#8b949e;font-size:12px;letter-spacing:1.5px;text-transform:uppercase;font-weight:600}
.card-value{font-size:28px;font-weight:700;line-height:1.2}

/* -------------------------------------------------------------- top header */
.session-header{
  display:flex;align-items:center;gap:32px;padding:24px 28px;
  background:linear-gradient(135deg,#141922 0%,#1a2233 100%);
  flex-wrap:wrap;
}
.efficiency-ring{
  width:140px;height:140px;border-radius:50%;
  display:flex;align-items:center;justify-content:center;
  flex-shrink:0;transition:background 0.6s ease;
}
.efficiency-inner{
  width:112px;height:112px;border-radius:50%;background:#141922;
  display:flex;flex-direction:column;align-items:center;justify-content:center;
}
.efficiency-num{font-size:36px;font-weight:800;line-height:1}
.efficiency-label{color:#8b949e;font-size:11px;margin-top:2px;text-transform:uppercase;letter-spacing:1px}
.session-stats{display:flex;gap:32px;flex-wrap:wrap}
.session-stat-val{font-size:24px;font-weight:700}
.session-stat-lbl{color:#8b949e;font-size:11px;text-transform:uppercase;letter-spacing:1px}
.btn-share{
  margin-left:auto;padding:8px 20px;border:1px solid #58a6ff;
  border-radius:8px;background:transparent;color:#58a6ff;cursor:pointer;
  font-size:13px;font-weight:600;transition:all 0.2s;
}
.btn-share:hover{background:#58a6ff;color:#0a0e14}

/* ----------------------------------------------------------- metric cards */
.metric-productive{border-left:3px solid #3fb950}
.metric-productive .card-value{color:#3fb950}
.metric-neutral{border-left:3px solid #8b949e}
.metric-neutral .card-value{color:#8b949e}
.metric-wasted{border-left:3px solid #f85149}
.metric-wasted .card-value{color:#f85149}
.metric-pct{font-size:16px;font-weight:600;margin-top:4px}

/* --------------------------------------------------------- chart containers */
.chart-wrap{position:relative;height:260px}
canvas{width:100%!important;height:100%!important}

/* --------------------------------------------------------------- timeline */
.timeline{max-height:400px;overflow-y:auto;padding-right:8px}
.timeline::-webkit-scrollbar{width:6px}
.timeline::-webkit-scrollbar-track{background:#0a0e14;border-radius:3px}
.timeline::-webkit-scrollbar-thumb{background:#1e2733;border-radius:3px}
.tl-item{
  display:flex;align-items:flex-start;gap:12px;padding:10px 0;
  border-bottom:1px solid #1e2733;
}
.tl-item:last-child{border-bottom:none}
.tl-icon{
  width:32px;height:32px;border-radius:8px;display:flex;
  align-items:center;justify-content:center;font-size:16px;flex-shrink:0;
}
.tl-icon-productive{background:rgba(63,185,80,0.15);color:#3fb950}
.tl-icon-neutral{background:rgba(139,148,158,0.15);color:#8b949e}
.tl-icon-wasted{background:rgba(248,81,73,0.15);color:#f85149}
.tl-body{flex:1;min-width:0}
.tl-desc{color:#e6edf3;font-size:13px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.tl-meta{display:flex;gap:12px;margin-top:2px;font-size:11px;color:#484f58}
.tl-badge{
  padding:1px 8px;border-radius:10px;font-size:10px;font-weight:600;
  text-transform:uppercase;letter-spacing:0.5px;
}
.tl-badge-productive{background:rgba(63,185,80,0.15);color:#3fb950}
.tl-badge-neutral{background:rgba(139,148,158,0.15);color:#8b949e}
.tl-badge-wasted{background:rgba(248,81,73,0.15);color:#f85149}
.tl-cost{color:#8b949e;font-size:12px;font-weight:600;flex-shrink:0}

/* --------------------------------------------------------------- insights */
.insight{
  display:flex;align-items:flex-start;gap:10px;padding:10px 12px;
  border-radius:8px;margin-bottom:8px;font-size:13px;
}
.insight-warning{background:rgba(210,153,34,0.1);border-left:3px solid #d29922;color:#d29922}
.insight-error{background:rgba(248,81,73,0.1);border-left:3px solid #f85149;color:#f85149}
.insight-info{background:rgba(88,166,255,0.1);border-left:3px solid #58a6ff;color:#58a6ff}
.insight-success{background:rgba(63,185,80,0.1);border-left:3px solid #3fb950;color:#3fb950}
.insight-icon{font-size:16px;flex-shrink:0;line-height:1.3}

/* -------------------------------------------------------- history sparkline */
.history-bar{display:flex;gap:2px;align-items:end;height:40px;margin:8px 0}
.history-col{
  flex:1;min-width:4px;max-width:16px;border-radius:2px 2px 0 0;
  transition:height 0.3s ease;cursor:pointer;position:relative;
}
.history-col:hover{opacity:0.8}
.history-summary{color:#8b949e;font-size:13px;margin-top:8px}
.history-summary span{color:#e6edf3;font-weight:600}

/* ----------------------------------------------------------- empty state */
.empty-state{
  text-align:center;padding:80px 20px;color:#484f58;
}
.empty-state h2{color:#8b949e;font-size:20px;margin-bottom:8px}
.empty-state p{font-size:14px;max-width:400px;margin:0 auto}
.empty-state code{
  display:block;background:#141922;border:1px solid #1e2733;
  border-radius:8px;padding:12px 16px;margin-top:16px;
  color:#58a6ff;font-size:13px;text-align:left;max-width:400px;
  margin-left:auto;margin-right:auto;
}

/* -------------------------------------------------------- loading/refresh */
.refresh-dot{
  width:8px;height:8px;border-radius:50%;background:#3fb950;
  display:inline-block;margin-right:6px;
  animation:pulse 2s ease-in-out infinite;
}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:0.3}}
.brand{color:#484f58;font-size:12px;text-align:center;padding:16px 0;letter-spacing:1px}

/* ----------------------------------------------------------- responsive */
@media(max-width:768px){
  .session-header{flex-direction:column;align-items:center;text-align:center}
  .session-stats{justify-content:center}
  .btn-share{margin:12px auto 0}
  .row{flex-direction:column}
}
</style>
</head>
<body>
<div class="dash" id="app">
  <div id="loading" class="empty-state">
    <h2>Loading session data...</h2>
  </div>
</div>

<script>
// ---------------------------------------------------------------- constants
const COLORS = {
  productive: '#3fb950',
  neutral: '#8b949e',
  wasted: '#f85149',
  accent: '#58a6ff',
  bg: '#0a0e14',
  cardBg: '#141922',
  border: '#1e2733',
  text: '#e6edf3',
  textMuted: '#484f58',
  textSecondary: '#8b949e',
};

const INSIGHT_ICONS = {
  warning: '\u26A0\uFE0F',
  error: '\u274C',
  info: '\u{1F4A1}',
  success: '\u2705',
};

// ---------------------------------------------------------------- state
let areaChart = null;
let barChart = null;
let refreshTimer = null;

// ---------------------------------------------------------------- helpers
function fmtCost(v) {
  if (v === undefined || v === null) return '$0.0000';
  return '$' + v.toFixed(4);
}

function fmtDuration(s) {
  if (!s || s < 0) s = 0;
  if (s < 60) return s + 's';
  const m = Math.floor(s / 60);
  const sec = s % 60;
  if (m < 60) return m + 'm ' + sec + 's';
  const h = Math.floor(m / 60);
  const min = m % 60;
  return h + 'h ' + min + 'm';
}

function fmtTime(ts) {
  if (!ts) return '';
  try {
    const d = new Date(ts);
    return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
  } catch { return ts; }
}

function effColor(eff) {
  if (eff >= 80) return COLORS.productive;
  if (eff >= 50) return '#d29922';
  return COLORS.wasted;
}

function conicGradient(eff) {
  const c = effColor(eff);
  const deg = eff * 3.6;
  return 'conic-gradient(' + c + ' ' + deg + 'deg, ' + COLORS.border + ' ' + deg + 'deg)';
}

function escapeHtml(s) {
  if (!s) return '';
  return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

// ---------------------------------------------------------------- render
function renderEmpty() {
  document.getElementById('app').innerHTML = `
    <div class="empty-state">
      <h2>No session data found</h2>
      <p>Start a Claude Code session and the dashboard will update automatically.</p>
      <code>
# Expected data file:<br>
# ~/.spent/claude-sessions.jsonl<br><br>
# Format (one JSON per line):<br>
{"ts":"...","event":"session_start","session":"abc123"}<br>
{"ts":"...","event":"tool_use","tool":"Edit","input_size":200,"output_size":100,"session":"abc123"}<br>
{"ts":"...","event":"session_end","session":"abc123"}
      </code>
      <p style="margin-top:16px;color:${COLORS.textSecondary}"><span class="refresh-dot"></span>Checking for data every 3 seconds</p>
    </div>
    <div class="brand">spent -- see what your AI really costs</div>
  `;
}

function renderDashboard(session, history) {
  const app = document.getElementById('app');
  const eff = session.efficiency || 0;

  let html = '';

  // ---- Row 1: Session header
  html += `
  <div class="card session-header row" style="margin-bottom:16px">
    <div class="efficiency-ring" style="background:${conicGradient(eff)}">
      <div class="efficiency-inner">
        <span class="efficiency-num" style="color:${effColor(eff)}">${eff}%</span>
        <span class="efficiency-label">Efficiency</span>
      </div>
    </div>
    <div>
      <div style="color:${COLORS.textSecondary};font-size:11px;text-transform:uppercase;letter-spacing:1px;margin-bottom:4px">
        <span class="refresh-dot"></span>Session ${escapeHtml(session.session_id || '')}
      </div>
      <div class="session-stats">
        <div>
          <div class="session-stat-val">${fmtDuration(session.duration_seconds)}</div>
          <div class="session-stat-lbl">Duration</div>
        </div>
        <div>
          <div class="session-stat-val">${fmtCost(session.total_cost)}</div>
          <div class="session-stat-lbl">Total Cost</div>
        </div>
        <div>
          <div class="session-stat-val">${session.event_count || 0}</div>
          <div class="session-stat-lbl">Actions</div>
        </div>
      </div>
    </div>
    <button class="btn-share" onclick="openShare()">Share Card</button>
  </div>`;

  // ---- Row 2: Three metric cards
  html += `<div class="row">
    <div class="card metric-productive">
      <div class="card-title">Productive</div>
      <div class="card-value">${fmtCost(session.productive_cost)}</div>
      <div class="metric-pct" style="color:#3fb950">${session.productive_pct || 0}% of total</div>
    </div>
    <div class="card metric-neutral">
      <div class="card-title">Neutral</div>
      <div class="card-value">${fmtCost(session.neutral_cost)}</div>
      <div class="metric-pct" style="color:#8b949e">${session.neutral_pct || 0}% of total</div>
    </div>
    <div class="card metric-wasted">
      <div class="card-title">Wasted</div>
      <div class="card-value">${fmtCost(session.wasted_cost)}</div>
      <div class="metric-pct" style="color:#f85149">${session.wasted_pct || 0}% of total</div>
    </div>
  </div>`;

  // ---- Row 3: Charts
  html += `<div class="row">
    <div class="card">
      <div class="card-title">Cost Over Time</div>
      <div class="chart-wrap"><canvas id="areaChart"></canvas></div>
    </div>
    <div class="card">
      <div class="card-title">Cost by Tool</div>
      <div class="chart-wrap"><canvas id="barChart"></canvas></div>
    </div>
  </div>`;

  // ---- Row 4: Timeline
  html += `<div class="card" style="margin-bottom:16px">
    <div class="card-header">
      <div class="card-title">Session Timeline</div>
      <div style="color:${COLORS.textMuted};font-size:12px">${(session.timeline || []).length} actions</div>
    </div>
    <div class="timeline" id="timeline">`;

  const tl = session.timeline || [];
  if (tl.length === 0) {
    html += '<div style="text-align:center;color:' + COLORS.textMuted + ';padding:24px">No actions recorded yet</div>';
  } else {
    for (const item of tl) {
      const cls = item.classification || 'neutral';
      html += `
      <div class="tl-item">
        <div class="tl-icon tl-icon-${cls}">${item.icon || '\u2022'}</div>
        <div class="tl-body">
          <div class="tl-desc">${escapeHtml(item.description)}</div>
          <div class="tl-meta">
            <span>${fmtTime(item.ts)}</span>
            <span class="tl-badge tl-badge-${cls}">${cls}</span>
          </div>
        </div>
        <div class="tl-cost">${fmtCost(item.cost)}</div>
      </div>`;
    }
  }
  html += '</div></div>';

  // ---- Row 5: Insights
  html += `<div class="card" style="margin-bottom:16px">
    <div class="card-title" style="margin-bottom:12px">Insights</div>`;

  const insights = session.insights || [];
  if (insights.length === 0) {
    html += '<div style="color:' + COLORS.textMuted + ';font-size:13px">Gathering data...</div>';
  } else {
    for (const ins of insights) {
      const t = ins.type || 'info';
      html += `<div class="insight insight-${t}">
        <span class="insight-icon">${INSIGHT_ICONS[t] || '\u{1F4A1}'}</span>
        <span>${escapeHtml(ins.text)}</span>
      </div>`;
    }
  }
  html += '</div>';

  // ---- Bottom: History
  const sessions = (history && history.sessions) || [];
  const avgEff = (history && history.average_efficiency) || 0;
  html += `<div class="card">
    <div class="card-title" style="margin-bottom:12px">Session History</div>`;

  if (sessions.length <= 1) {
    html += `<div style="color:${COLORS.textMuted};font-size:13px">Complete more sessions to see trends here.</div>`;
  } else {
    html += '<div class="history-bar" id="historyBar">';
    const maxEff = Math.max(...sessions.map(s => s.efficiency || 0), 1);
    for (let i = sessions.length - 1; i >= 0; i--) {
      const s = sessions[i];
      const h = Math.max(((s.efficiency || 0) / 100) * 40, 2);
      const c = effColor(s.efficiency || 0);
      const isCurrent = i === 0;
      const opacity = isCurrent ? '1' : '0.6';
      const border = isCurrent ? 'border:1px solid ' + COLORS.accent : '';
      html += `<div class="history-col" style="height:${h}px;background:${c};opacity:${opacity};${border}" title="${s.session}: ${s.efficiency}% efficiency, ${fmtCost(s.total_cost)}"></div>`;
    }
    html += '</div>';
    html += `<div class="history-summary">Your average: <span>${avgEff}%</span>. This session: <span style="color:${effColor(eff)}">${eff}%</span></div>`;
  }
  html += '</div>';

  html += '<div class="brand">spent -- see what your AI really costs</div>';

  app.innerHTML = html;

  // ---- render charts after DOM is ready
  renderAreaChart(session.cost_over_time || []);
  renderBarChart(session.cost_by_tool || {});
}

// ---------------------------------------------------------------- charts
function renderAreaChart(data) {
  const canvas = document.getElementById('areaChart');
  if (!canvas) return;
  if (areaChart) { areaChart.destroy(); areaChart = null; }

  const labels = data.map((d, i) => {
    if (d.ts) { try { return fmtTime(d.ts); } catch {} }
    return '' + (i + 1);
  });

  areaChart = new Chart(canvas, {
    type: 'line',
    data: {
      labels: labels,
      datasets: [
        {
          label: 'Productive',
          data: data.map(d => d.productive || 0),
          borderColor: COLORS.productive,
          backgroundColor: COLORS.productive + '33',
          fill: true,
          tension: 0.3,
          pointRadius: 0,
          borderWidth: 2,
        },
        {
          label: 'Neutral',
          data: data.map(d => d.neutral || 0),
          borderColor: COLORS.neutral,
          backgroundColor: COLORS.neutral + '33',
          fill: true,
          tension: 0.3,
          pointRadius: 0,
          borderWidth: 2,
        },
        {
          label: 'Wasted',
          data: data.map(d => d.wasted || 0),
          borderColor: COLORS.wasted,
          backgroundColor: COLORS.wasted + '33',
          fill: true,
          tension: 0.3,
          pointRadius: 0,
          borderWidth: 2,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: 'index', intersect: false },
      plugins: {
        legend: {
          display: true,
          position: 'top',
          labels: { color: COLORS.textSecondary, boxWidth: 12, padding: 12, font: { size: 11 } },
        },
        tooltip: {
          backgroundColor: '#1a2233',
          titleColor: COLORS.text,
          bodyColor: COLORS.textSecondary,
          borderColor: COLORS.border,
          borderWidth: 1,
          callbacks: {
            label: function(ctx) {
              return ctx.dataset.label + ': ' + fmtCost(ctx.parsed.y);
            }
          }
        },
      },
      scales: {
        x: {
          display: true,
          grid: { color: COLORS.border + '40' },
          ticks: { color: COLORS.textMuted, maxTicksLimit: 8, font: { size: 10 } },
        },
        y: {
          display: true,
          grid: { color: COLORS.border + '40' },
          ticks: {
            color: COLORS.textMuted,
            font: { size: 10 },
            callback: function(v) { return '$' + v.toFixed(4); },
          },
        },
      },
    },
  });
}

function renderBarChart(costByTool) {
  const canvas = document.getElementById('barChart');
  if (!canvas) return;
  if (barChart) { barChart.destroy(); barChart = null; }

  const tools = Object.keys(costByTool);
  const costs = Object.values(costByTool);

  const toolColors = {
    'Edit': '#3fb950',
    'Write': '#56d364',
    'Agent': '#2ea043',
    'Read': '#8b949e',
    'Grep': '#6e7681',
    'Glob': '#484f58',
    'Bash': '#d29922',
    'TaskCreate': '#6e7681',
    'TaskUpdate': '#6e7681',
  };

  const bgColors = tools.map(t => (toolColors[t] || COLORS.accent) + 'cc');
  const borderColors = tools.map(t => toolColors[t] || COLORS.accent);

  barChart = new Chart(canvas, {
    type: 'bar',
    data: {
      labels: tools,
      datasets: [{
        data: costs,
        backgroundColor: bgColors,
        borderColor: borderColors,
        borderWidth: 1,
        borderRadius: 4,
      }],
    },
    options: {
      indexAxis: 'y',
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: {
          backgroundColor: '#1a2233',
          titleColor: COLORS.text,
          bodyColor: COLORS.textSecondary,
          borderColor: COLORS.border,
          borderWidth: 1,
          callbacks: {
            label: function(ctx) { return fmtCost(ctx.parsed.x); },
          },
        },
      },
      scales: {
        x: {
          grid: { color: COLORS.border + '40' },
          ticks: {
            color: COLORS.textMuted,
            font: { size: 10 },
            callback: function(v) { return '$' + v.toFixed(4); },
          },
        },
        y: {
          grid: { display: false },
          ticks: { color: COLORS.textSecondary, font: { size: 12, weight: '600' } },
        },
      },
    },
  });
}

// ---------------------------------------------------------------- share
function openShare() {
  window.open('/api/share', '_blank', 'width=560,height=480');
}

// ---------------------------------------------------------------- data fetch
async function fetchData() {
  try {
    const [sessionRes, historyRes] = await Promise.all([
      fetch('/api/session'),
      fetch('/api/history'),
    ]);
    const session = await sessionRes.json();
    const history = await historyRes.json();

    if (session.error && !session.data) {
      renderEmpty();
      return;
    }

    renderDashboard(session, history);
  } catch (err) {
    console.error('Fetch error:', err);
    renderEmpty();
  }
}

// ---------------------------------------------------------------- init
fetchData();
refreshTimer = setInterval(fetchData, 3000);
</script>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# Server entrypoint
# ---------------------------------------------------------------------------

def serve(port: int = DEFAULT_PORT, open_browser: bool = True) -> None:
    """Start the Claude Code dashboard server."""
    JSONL_PATH.parent.mkdir(parents=True, exist_ok=True)

    server = HTTPServer(("127.0.0.1", port), ClaudeDashboardHandler)
    url = f"http://localhost:{port}"

    print("\n  Claude Code Dashboard")
    print(f"  {url}")
    print(f"  Data: {JSONL_PATH}")
    print("\n  Press Ctrl+C to stop.\n")

    if open_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  Dashboard stopped.")
        server.server_close()
