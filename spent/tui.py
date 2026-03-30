"""Terminal UI -- persistent cost dashboard for split terminal panes.

Run in a side terminal pane alongside Claude Code:
    spent cc live

Designed for narrow panes (40+ chars wide). Auto-refreshes every 2s.
"""

from __future__ import annotations

import sys
import time
from datetime import datetime

TOOL_ICONS = {
    "Edit": "✏", "Write": "✏", "Read": "📖", "Bash": "⌘",
    "Grep": "🔍", "Glob": "🔍", "Agent": "🤖",
    "TaskCreate": "📋", "TaskUpdate": "📋",
}


def run_tui(*, interval: float = 2.0) -> None:
    """Run the persistent terminal dashboard."""
    try:
        from rich.console import Console
        from rich.live import Live
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

    try:
        from .claude_tracker import ClaudeTracker
        from .cost_engine import generate_tips

        tracker = ClaudeTracker()
        data = tracker.get_current_session()
    except Exception as exc:
        return Panel(
            Align.center(
                Text(
                    f"Error loading session data:\n{exc}\n\nCheck: spent cc setup",
                    style="bold red",
                )
            ),
            title="[bold blue]spent[/]",
            border_style="red",
        )

    if not data.get("session_id"):
        return Panel(
            Align.center(
                Text(
                    "Waiting for Claude Code session...\n\nRun: spent cc setup",
                    style="dim",
                )
            ),
            title="[bold blue]spent[/]",
            border_style="blue",
        )

    # Derive score, tips, and efficiency breakdown from session data.
    try:
        score = tracker.get_efficiency_score(data)
    except Exception:
        score = 0.0

    eff = data.get("efficiency", {})
    productive_cost = eff.get("productive", 0.0)
    neutral_cost = eff.get("neutral", 0.0)
    wasted_cost = eff.get("wasted", 0.0)
    total_cost = data.get("total_cost", 0.0)
    tool_uses = data.get("tool_uses", 0)
    duration_minutes = data.get("duration_minutes", 0.0)
    by_tool = data.get("by_tool", {})
    timeline = data.get("timeline", [])

    tips = generate_tips(by_tool, total_cost, wasted_cost, timeline)

    # Narrow mode (< 65 chars) vs wide mode.
    narrow = width < 65

    # -- Score header --
    score_int = int(score)
    score_color = "green" if score_int >= 70 else "yellow" if score_int >= 40 else "red"
    cost_str = f"${total_cost:.4f}"
    duration_str = _fmt_duration(duration_minutes * 60)

    score_bar = _make_bar(score_int, 20)
    header_text = Text()
    header_text.append(f" {score_int}% ", style=f"bold {score_color} reverse")
    header_text.append(f"  {cost_str}", style="bold white")
    header_text.append(f"  {duration_str}", style="dim")
    header_text.append(f"  {tool_uses} tools", style="dim")
    header_text.append("\n ")
    header_text.append_text(Text.from_markup(score_bar))

    header = Panel(header_text, title="[bold]spent[/]", border_style="blue", height=4)

    # -- Efficiency bars --
    eff_lines = Text()
    if total_cost > 0:
        p_pct = int(productive_cost / total_cost * 100)
        n_pct = int(neutral_cost / total_cost * 100)
        w_pct = int(wasted_cost / total_cost * 100)
        bar_w = max(width - 30, 10)

        p_bar = "█" * max(1, int(p_pct / 100 * bar_w))
        n_bar = "█" * max(0, int(n_pct / 100 * bar_w))
        w_bar = "█" * max(0, int(w_pct / 100 * bar_w))

        eff_lines.append(" Productive ", style="bold green")
        eff_lines.append(f"${productive_cost:.4f} ", style="green")
        eff_lines.append(f"{p_bar}\n", style="green")
        eff_lines.append(" Neutral    ", style="bold dim")
        eff_lines.append(f"${neutral_cost:.4f} ", style="dim")
        eff_lines.append(f"{n_bar}\n", style="dim")
        eff_lines.append(" Wasted     ", style="bold red")
        eff_lines.append(f"${wasted_cost:.4f} ", style="red")
        eff_lines.append(f"{w_bar}", style="red")
    else:
        eff_lines.append(" No data yet", style="dim")

    eff_panel = Panel(eff_lines, title="[dim]Breakdown[/]", border_style="dim", height=5)

    # -- Tool breakdown --
    tool_table = Table(
        show_header=True,
        header_style="bold cyan",
        box=None,
        padding=(0, 1),
        expand=True,
    )
    tool_table.add_column("Tool", style="white", max_width=12)
    tool_table.add_column("#", justify="right", style="dim", max_width=4)
    tool_table.add_column("Cost", justify="right", style="bold", max_width=10)
    if not narrow:
        tool_table.add_column("", max_width=15)

    for tool, info in sorted(
        by_tool.items(), key=lambda x: x[1].get("cost", 0), reverse=True
    )[:6]:
        icon = TOOL_ICONS.get(tool, "·")
        pct = int(info["cost"] / total_cost * 100) if total_cost > 0 else 0
        mini_bar = "█" * max(1, pct // 10) + "░" * (10 - max(1, pct // 10))
        row = [f"{icon} {tool}", str(info["count"]), f"${info['cost']:.4f}"]
        if not narrow:
            row.append(f"[green]{mini_bar}[/] {pct}%")
        tool_table.add_row(*row)

    tools_panel = Panel(tool_table, title="[dim]By Tool[/]", border_style="dim")

    # -- Timeline (last N actions) --
    max_timeline = max(3, (height - 18) // 2)
    timeline_text = Text()
    for ev in timeline[-max_timeline:]:
        icon = TOOL_ICONS.get(ev["tool"], "·")
        ts = ev["ts"].split("T")[1][:8] if "T" in ev["ts"] else ev["ts"]
        status = ev["status"]
        status_style = (
            "green" if status == "productive"
            else "red" if status == "wasted"
            else "dim"
        )

        timeline_text.append(f" {icon} ", style="bold")
        timeline_text.append(f"{ts} ", style="dim")
        timeline_text.append(f"{ev['tool']:<8}", style="white")
        timeline_text.append(f" ${ev['cost']:.4f}", style="bold")
        timeline_text.append(f"  {status}\n", style=status_style)

    if not timeline:
        timeline_text.append(" Waiting for actions...", style="dim")

    timeline_panel = Panel(timeline_text, title="[dim]Timeline[/]", border_style="dim")

    # -- Tips --
    tips_text = Text()
    for tip in tips[:3]:
        tips_text.append(f" 💡 {tip}\n", style="yellow")
    if not tips:
        tips_text.append(" Looking good!", style="green")

    tips_panel = Panel(
        tips_text,
        title="[dim]Tips[/]",
        border_style="dim",
        height=max(3, len(tips[:3]) + 2),
    )

    # -- Compose layout --
    now = datetime.now().strftime("%H:%M:%S")
    layout = Layout()
    layout.split_column(
        Layout(header, name="header", size=4),
        Layout(eff_panel, name="efficiency", size=5),
        Layout(tools_panel, name="tools", size=min(9, len(by_tool) + 3)),
        Layout(timeline_panel, name="timeline"),
        Layout(tips_panel, name="tips", size=max(3, len(tips[:3]) + 2)),
        Layout(
            Text(f" [dim]spent {now} | Ctrl+C to exit[/]"),
            name="footer",
            size=1,
        ),
    )

    return layout


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
