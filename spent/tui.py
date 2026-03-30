"""Terminal UI -- persistent cost dashboard for split terminal panes.

Run in a side terminal pane alongside Claude Code:
    spent cc live

Designed for narrow panes (40+ chars wide). Auto-refreshes every 2s.
"""

from __future__ import annotations

import json
import sys
import time
from datetime import datetime
from pathlib import Path
from collections import defaultdict

LOG_PATH = Path.home() / ".spent" / "claude-sessions.jsonl"

# Cost estimation constants
CHARS_PER_TOKEN = 4
BASE_OVERHEAD = 500
CONTEXT_GROWTH = 200
INPUT_PRICE = 3.00 / 1_000_000   # Sonnet: $3/1M input
OUTPUT_PRICE = 15.00 / 1_000_000  # Sonnet: $15/1M output

TOOL_ICONS = {
    "Edit": "✏", "Write": "✏", "Read": "📖", "Bash": "⌘",
    "Grep": "🔍", "Glob": "🔍", "Agent": "🤖",
    "TaskCreate": "📋", "TaskUpdate": "📋",
}

PRODUCTIVE_TOOLS = {"Edit", "Write", "Agent", "MultiEdit", "NotebookEdit"}
WASTED_KEYWORDS = {"error", "Error", "ERROR", "failed", "Failed", "FAILED", "traceback", "Traceback"}


def run_tui(*, interval: float = 2.0) -> None:
    """Run the persistent terminal dashboard."""
    try:
        from rich.console import Console
        from rich.live import Live
        from rich.layout import Layout
        from rich.panel import Panel
        from rich.table import Table
        from rich.text import Text
        from rich.align import Align
    except ImportError:
        print("Install rich: pip install rich", file=sys.stderr)
        sys.exit(1)

    console = Console(stderr=True)

    try:
        with Live(console=console, refresh_per_second=1, screen=True) as live:
            while True:
                layout = _build_layout(console.width, console.height)
                live.update(layout)
                time.sleep(interval)
    except KeyboardInterrupt:
        pass


def _build_layout(width: int, height: int):
    from rich.layout import Layout
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text
    from rich.align import Align

    events = _read_events()
    session_id, session_events = _get_latest_session(events)
    data = _compute(session_events) if session_events else None

    if data is None:
        return Panel(
            Align.center(Text("Waiting for Claude Code session...\n\nRun: spent cc setup", style="dim")),
            title="[bold blue]spent[/]",
            border_style="blue",
        )

    # Narrow mode (< 60 chars) vs wide mode
    narrow = width < 65

    # ── Score header ──
    score = data["score"]
    score_color = "green" if score >= 70 else "yellow" if score >= 40 else "red"
    cost_str = f"${data['total_cost']:.4f}"
    duration_str = _fmt_duration(data["duration_sec"])

    score_bar = _make_bar(score, 20)
    header_text = Text()
    header_text.append(f" {score}% ", style=f"bold {score_color} reverse")
    header_text.append(f"  {cost_str}", style="bold white")
    header_text.append(f"  {duration_str}", style="dim")
    header_text.append(f"  {data['tool_uses']} tools", style="dim")
    header_text.append(f"\n {score_bar}")

    header = Panel(header_text, title="[bold]spent[/]", border_style="blue", height=4)

    # ── Efficiency bars ──
    p = data["productive"]
    n = data["neutral"]
    w = data["wasted"]
    total = data["total_cost"]

    eff_lines = Text()
    if total > 0:
        p_pct = int(p / total * 100)
        n_pct = int(n / total * 100)
        w_pct = int(w / total * 100)
        bar_w = max(width - 30, 10)

        p_bar = "█" * max(1, int(p_pct / 100 * bar_w))
        n_bar = "█" * max(0, int(n_pct / 100 * bar_w))
        w_bar = "█" * max(0, int(w_pct / 100 * bar_w))

        eff_lines.append(f" Productive ", style="bold green")
        eff_lines.append(f"${p:.4f} ", style="green")
        eff_lines.append(f"{p_bar}\n", style="green")
        eff_lines.append(f" Neutral    ", style="bold dim")
        eff_lines.append(f"${n:.4f} ", style="dim")
        eff_lines.append(f"{n_bar}\n", style="dim")
        eff_lines.append(f" Wasted     ", style="bold red")
        eff_lines.append(f"${w:.4f} ", style="red")
        eff_lines.append(f"{w_bar}", style="red")
    else:
        eff_lines.append(" No data yet", style="dim")

    eff_panel = Panel(eff_lines, title="[dim]Breakdown[/]", border_style="dim", height=5)

    # ── Tool breakdown ──
    tool_table = Table(show_header=True, header_style="bold cyan", box=None, padding=(0, 1), expand=True)
    tool_table.add_column("Tool", style="white", max_width=12)
    tool_table.add_column("#", justify="right", style="dim", max_width=4)
    tool_table.add_column("Cost", justify="right", style="bold", max_width=10)
    if not narrow:
        tool_table.add_column("", max_width=15)

    for tool, info in sorted(data["by_tool"].items(), key=lambda x: x[1]["cost"], reverse=True)[:6]:
        icon = TOOL_ICONS.get(tool, "·")
        pct = int(info["cost"] / total * 100) if total > 0 else 0
        mini_bar = "█" * max(1, pct // 10) + "░" * (10 - max(1, pct // 10))
        row = [f"{icon} {tool}", str(info["count"]), f"${info['cost']:.4f}"]
        if not narrow:
            row.append(f"[green]{mini_bar}[/] {pct}%")
        tool_table.add_row(*row)

    tools_panel = Panel(tool_table, title="[dim]By Tool[/]", border_style="dim")

    # ── Timeline (last N actions) ──
    max_timeline = max(3, (height - 18) // 2)
    timeline_text = Text()
    for ev in data["timeline"][-max_timeline:]:
        icon = TOOL_ICONS.get(ev["tool"], "·")
        ts = ev["ts"].split("T")[1][:8] if "T" in ev["ts"] else ev["ts"]
        status = ev["status"]
        status_style = "green" if status == "productive" else "red" if status == "wasted" else "dim"

        timeline_text.append(f" {icon} ", style="bold")
        timeline_text.append(f"{ts} ", style="dim")
        timeline_text.append(f"{ev['tool']:<8}", style="white")
        timeline_text.append(f" ${ev['cost']:.4f}", style="bold")
        timeline_text.append(f"  {status}\n", style=status_style)

    if not data["timeline"]:
        timeline_text.append(" Waiting for actions...", style="dim")

    timeline_panel = Panel(timeline_text, title="[dim]Timeline[/]", border_style="dim")

    # ── Tips ──
    tips = data.get("tips", [])
    tips_text = Text()
    for tip in tips[:3]:
        tips_text.append(f" 💡 {tip}\n", style="yellow")
    if not tips:
        tips_text.append(" Looking good!", style="green")

    tips_panel = Panel(tips_text, title="[dim]Tips[/]", border_style="dim", height=max(3, len(tips[:3]) + 2))

    # ── Compose layout ──
    now = datetime.now().strftime("%H:%M:%S")
    layout = Layout()
    layout.split_column(
        Layout(header, name="header", size=4),
        Layout(eff_panel, name="efficiency", size=5),
        Layout(tools_panel, name="tools", size=min(9, len(data["by_tool"]) + 3)),
        Layout(timeline_panel, name="timeline"),
        Layout(tips_panel, name="tips", size=max(3, len(tips[:3]) + 2)),
        Layout(Text(f" [dim]spent {now} | Ctrl+C to exit[/]"), name="footer", size=1),
    )

    return layout


def _read_events() -> list[dict]:
    if not LOG_PATH.exists():
        return []
    events = []
    try:
        for line in LOG_PATH.read_text(encoding="utf-8").strip().split("\n"):
            if line.strip():
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except OSError:
        pass
    return events


def _get_latest_session(events: list[dict]) -> tuple[str, list[dict]]:
    if not events:
        return ("", [])
    sessions: dict[str, list[dict]] = defaultdict(list)
    for ev in events:
        sid = ev.get("session", "unknown")
        sessions[sid].append(ev)
    last_sid = list(sessions.keys())[-1]
    return (last_sid, sessions[last_sid])


def _compute(events: list[dict]) -> dict:
    tool_events = [e for e in events if e.get("event") == "tool_use"]
    if not tool_events:
        return {
            "score": 0, "total_cost": 0, "duration_sec": 0, "tool_uses": 0,
            "productive": 0, "neutral": 0, "wasted": 0,
            "by_tool": {}, "timeline": [], "tips": [],
        }

    # Parse timestamps
    first_ts = events[0].get("ts", "")
    last_ts = events[-1].get("ts", "")
    try:
        t0 = datetime.fromisoformat(first_ts)
        t1 = datetime.fromisoformat(last_ts)
        duration_sec = max(1, (t1 - t0).total_seconds())
    except (ValueError, TypeError):
        duration_sec = 1

    # Compute costs and classify
    by_tool: dict[str, dict] = {}
    timeline = []
    productive_cost = 0.0
    neutral_cost = 0.0
    wasted_cost = 0.0
    read_times: dict[str, float] = {}

    for i, ev in enumerate(tool_events):
        tool = ev.get("tool", "?")
        in_size = ev.get("input_size", 0)
        out_size = ev.get("output_size", 0)

        in_tok = max(in_size // CHARS_PER_TOKEN, BASE_OVERHEAD) + BASE_OVERHEAD + (i * CONTEXT_GROWTH)
        out_tok = max(out_size // CHARS_PER_TOKEN, 1)
        cost = in_tok * INPUT_PRICE + out_tok * OUTPUT_PRICE

        # Classify
        status = "neutral"
        output_text = ev.get("output_text", "")
        ts_str = ev.get("ts", "")

        if tool in PRODUCTIVE_TOOLS:
            status = "productive"
        elif tool == "Bash":
            if any(kw in output_text for kw in WASTED_KEYWORDS):
                status = "wasted"
            else:
                status = "neutral"
        elif tool == "Read":
            # Detect repeated reads
            try:
                ts_float = datetime.fromisoformat(ts_str).timestamp()
                target = f"{in_size}"
                if target in read_times and (ts_float - read_times[target]) < 60:
                    status = "wasted"
                read_times[target] = ts_float
            except (ValueError, TypeError):
                pass

        if status == "productive":
            productive_cost += cost
        elif status == "wasted":
            wasted_cost += cost
        else:
            neutral_cost += cost

        if tool not in by_tool:
            by_tool[tool] = {"count": 0, "cost": 0.0}
        by_tool[tool]["count"] += 1
        by_tool[tool]["cost"] += cost

        timeline.append({
            "ts": ts_str,
            "tool": tool,
            "cost": cost,
            "status": status,
        })

    total_cost = productive_cost + neutral_cost + wasted_cost
    score = int((productive_cost / total_cost * 100) if total_cost > 0 else 100)

    # Generate tips
    tips = []
    if wasted_cost > 0:
        tips.append(f"${wasted_cost:.4f} wasted on failed/repeated actions")
    for tool, info in sorted(by_tool.items(), key=lambda x: x[1]["cost"], reverse=True)[:1]:
        if info["cost"] > total_cost * 0.4:
            tips.append(f"{tool} is {int(info['cost']/total_cost*100)}% of your spend")
    wasted_events = [t for t in timeline if t["status"] == "wasted"]
    if len(wasted_events) >= 3:
        tips.append(f"{len(wasted_events)} actions classified as wasted")

    return {
        "score": score,
        "total_cost": total_cost,
        "duration_sec": duration_sec,
        "tool_uses": len(tool_events),
        "productive": productive_cost,
        "neutral": neutral_cost,
        "wasted": wasted_cost,
        "by_tool": by_tool,
        "timeline": timeline,
        "tips": tips,
    }


def _make_bar(pct: int, width: int) -> str:
    filled = int(pct / 100 * width)
    empty = width - filled
    if pct >= 70:
        color = "green"
    elif pct >= 40:
        color = "yellow"
    else:
        color = "red"
    return f"[{color}]{'█' * filled}[/][dim]{'░' * empty}[/] "


def _fmt_duration(seconds: float) -> str:
    if seconds < 60:
        return f"{int(seconds)}s"
    m = int(seconds // 60)
    s = int(seconds % 60)
    if m < 60:
        return f"{m}m{s}s"
    h = m // 60
    m = m % 60
    return f"{h}h{m}m"
