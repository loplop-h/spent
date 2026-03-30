"""Live cost ticker -- compact real-time display for terminal integration."""

from __future__ import annotations

import sys
import time
from datetime import datetime, timezone

from .storage import Storage


def run_ticker(*, compact: bool = False, interval: float = 1.0) -> None:
    """Run a single-line cost ticker that updates in real-time.

    Perfect for running in a split terminal pane alongside Claude Code,
    Cursor, or any AI coding tool.
    """
    storage = Storage()

    try:
        while True:
            records = storage.get_today()
            total_cost = sum(r["cost"] for r in records)
            total_tokens = sum(r["input_tokens"] + r["output_tokens"] for r in records)
            total_calls = len(records)

            # Find most recent call
            last_model = records[-1]["model"] if records else "-"
            last_cost = records[-1]["cost"] if records else 0

            if compact:
                # Single line, perfect for status bars
                line = (
                    f"\r\033[K"  # clear line
                    f"\033[36m$\033[0m{total_cost:.4f} "
                    f"\033[90m|\033[0m {total_calls} calls "
                    f"\033[90m|\033[0m {total_tokens:,} tok "
                    f"\033[90m|\033[0m last: {last_model} ${last_cost:.4f}"
                )
                sys.stderr.write(line)
                sys.stderr.flush()
            else:
                _print_ticker_frame(total_cost, total_calls, total_tokens, last_model, last_cost, records)

            time.sleep(interval)

    except KeyboardInterrupt:
        if compact:
            sys.stderr.write("\r\033[K")
        else:
            print("\n")


def run_panel(*, interval: float = 2.0) -> None:
    """Run a compact Rich panel that updates in real-time.

    Shows a small widget with per-model breakdown, perfect for
    a side terminal pane.
    """
    try:
        from rich.console import Console
        from rich.live import Live
        from rich.table import Table
        from rich.panel import Panel
        from rich.text import Text
    except ImportError:
        print("Install rich: pip install rich", file=sys.stderr)
        sys.exit(1)

    console = Console(stderr=True)
    storage = Storage()

    try:
        with Live(console=console, refresh_per_second=1) as live:
            while True:
                records = storage.get_today()
                widget = _build_panel(records)
                live.update(widget)
                time.sleep(interval)
    except KeyboardInterrupt:
        pass


def get_statusline() -> str:
    """Return a single-line status string for Claude Code statusline integration.

    Called by the Claude Code statusline hook.
    """
    storage = Storage()
    records = storage.get_today()

    if not records:
        return "spent: $0.00 | 0 calls"

    total_cost = sum(r["cost"] for r in records)
    total_calls = len(records)
    total_tokens = sum(r["input_tokens"] + r["output_tokens"] for r in records)

    return f"spent: ${total_cost:.4f} | {total_calls} calls | {total_tokens:,} tok"


def _print_ticker_frame(
    total_cost: float,
    total_calls: int,
    total_tokens: int,
    last_model: str,
    last_cost: float,
    records: list[dict],
) -> None:
    """Print a compact multi-line ticker frame."""
    try:
        from rich.console import Console
        from rich.text import Text
        from rich.panel import Panel

        console = Console(stderr=True)

        # Build per-model summary
        by_model: dict[str, dict] = {}
        for r in records:
            m = r["model"]
            if m not in by_model:
                by_model[m] = {"cost": 0.0, "calls": 0}
            by_model[m]["cost"] += r["cost"]
            by_model[m]["calls"] += 1

        lines = [f"[bold cyan]${total_cost:.4f}[/] | {total_calls} calls | {total_tokens:,} tokens"]
        for model, data in sorted(by_model.items(), key=lambda x: x[1]["cost"], reverse=True)[:5]:
            pct = (data["cost"] / total_cost * 100) if total_cost > 0 else 0
            lines.append(f"  [dim]{model}[/]: ${data['cost']:.4f} ({pct:.0f}%) x{data['calls']}")

        now = datetime.now().strftime("%H:%M:%S")
        content = "\n".join(lines)

        console.clear()
        console.print(Panel(content, title=f"[bold]spent[/] {now}", border_style="blue", width=60))

    except ImportError:
        # Fallback without Rich
        sys.stderr.write(f"\033[2J\033[H")  # clear screen
        sys.stderr.write(f"spent | ${total_cost:.4f} | {total_calls} calls | {total_tokens:,} tok\n")
        sys.stderr.flush()


def _build_panel(records: list[dict]):
    """Build a compact Rich panel for the live widget."""
    from rich.table import Table
    from rich.panel import Panel

    total_cost = sum(r["cost"] for r in records)
    total_tokens = sum(r["input_tokens"] + r["output_tokens"] for r in records)
    total_calls = len(records)

    by_model: dict[str, dict] = {}
    for r in records:
        m = r["model"]
        if m not in by_model:
            by_model[m] = {"cost": 0.0, "calls": 0, "tokens": 0}
        by_model[m]["cost"] += r["cost"]
        by_model[m]["calls"] += 1
        by_model[m]["tokens"] += r["input_tokens"] + r["output_tokens"]

    table = Table(show_header=True, header_style="bold cyan", box=None, padding=(0, 1))
    table.add_column("Model", max_width=25)
    table.add_column("$", justify="right", style="bold")
    table.add_column("#", justify="right", style="dim")

    for model, data in sorted(by_model.items(), key=lambda x: x[1]["cost"], reverse=True)[:8]:
        table.add_row(
            model[:25],
            f"${data['cost']:.4f}",
            str(data["calls"]),
        )

    if not records:
        table.add_row("[dim]waiting...[/]", "", "")

    now = datetime.now().strftime("%H:%M:%S")
    color = "red" if total_cost > 1 else "yellow" if total_cost > 0.1 else "green"

    return Panel(
        table,
        title=f"[bold]spent[/] [{color}]${total_cost:.4f}[/] | {total_calls} calls | {now}",
        border_style="blue",
        width=50,
    )
