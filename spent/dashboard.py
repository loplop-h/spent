"""Rich terminal dashboard and summary display."""

from __future__ import annotations

import sys
import time

from .storage import Storage


def print_summary(data: dict) -> None:
    """Print a beautiful cost summary to stderr."""
    try:
        from rich.console import Console
        from rich.panel import Panel
        from rich.table import Table
        from rich.text import Text
        _print_rich(data)
    except ImportError:
        _print_plain(data)


def _print_rich(data: dict) -> None:
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text

    console = Console(stderr=True)
    console.print()

    # Header
    total = data["total_cost"]
    calls = data["total_calls"]
    tokens = data["total_tokens"]
    duration = data["duration_seconds"]

    header_lines = [
        f"[bold white]Total Cost:[/]    [bold {'red' if total > 1 else 'green'}]${total:.4f}[/]",
        f"[bold white]Tokens:[/]        [dim]{tokens:,}[/]  ({data['total_input_tokens']:,} in / {data['total_output_tokens']:,} out)",
        f"[bold white]API Calls:[/]     [dim]{calls}[/]",
        f"[bold white]Duration:[/]      [dim]{_fmt_duration(duration)}[/]",
    ]

    if data.get("budget") is not None:
        pct = (total / data["budget"]) * 100 if data["budget"] > 0 else 0
        color = "red" if pct >= 100 else "yellow" if pct >= 80 else "green"
        header_lines.append(
            f"[bold white]Budget:[/]        [{color}]${total:.4f} / ${data['budget']:.2f} ({pct:.0f}%)[/]"
        )

    header = "\n".join(header_lines)

    # Model breakdown table
    by_model = data.get("by_model", {})
    if by_model:
        table = Table(show_header=True, header_style="bold cyan", box=None, padding=(0, 2))
        table.add_column("Model", style="white")
        table.add_column("Calls", justify="right", style="dim")
        table.add_column("Tokens", justify="right", style="dim")
        table.add_column("Cost", justify="right", style="bold")
        table.add_column("Share", justify="right")

        sorted_models = sorted(by_model.items(), key=lambda x: x[1]["cost"], reverse=True)
        for model, info in sorted_models:
            share = (info["cost"] / total * 100) if total > 0 else 0
            bar = _bar(share)
            table.add_row(
                model,
                str(info["calls"]),
                f"{info['input_tokens'] + info['output_tokens']:,}",
                f"${info['cost']:.4f}",
                f"{bar} {share:.0f}%",
            )

    # Savings section
    savings = data.get("savings", [])
    savings_text = ""
    if savings:
        total_savings = sum(s["savings_usd"] for s in savings)
        savings_lines = []
        for s in savings:
            savings_lines.append(
                f"  [yellow]{s['from']}[/] -> [green]{s['to']}[/]: "
                f"save ${s['savings_usd']:.4f} ({s['savings_pct']}%) on {s['calls_affected']} calls"
            )
        savings_text = (
            f"\n[bold yellow]Savings Opportunities:[/] [bold green]~${total_savings:.4f}[/]\n"
            + "\n".join(savings_lines)
        )

    # Compose panel
    content = header
    if by_model:
        console.print(
            Panel(content, title="[bold]spent[/]", subtitle=f"session {data['session_id']}", border_style="blue")
        )
        console.print(table)
    else:
        console.print(Panel(content, title="[bold]spent[/]", border_style="blue"))

    if savings_text:
        console.print(savings_text)

    console.print()


def _print_plain(data: dict) -> None:
    """Fallback when rich is not installed."""
    total = data["total_cost"]
    calls = data["total_calls"]
    tokens = data["total_tokens"]

    print("\n--- spent ---", file=sys.stderr)
    print(f"Total Cost:  ${total:.4f}", file=sys.stderr)
    print(f"Tokens:      {tokens:,}", file=sys.stderr)
    print(f"API Calls:   {calls}", file=sys.stderr)

    for model, info in data.get("by_model", {}).items():
        share = (info["cost"] / total * 100) if total > 0 else 0
        print(f"  {model}: ${info['cost']:.4f} ({share:.0f}%)", file=sys.stderr)

    for s in data.get("savings", []):
        print(
            f"  Tip: {s['from']} -> {s['to']}: save ${s['savings_usd']:.4f} ({s['savings_pct']}%)",
            file=sys.stderr,
        )
    print("-------------\n", file=sys.stderr)


def live_dashboard() -> None:
    """Real-time dashboard showing costs as they come in."""
    try:
        from rich.console import Console
        from rich.live import Live
        from rich.table import Table
        from rich.panel import Panel
    except ImportError:
        print("Install rich for the live dashboard: pip install rich", file=sys.stderr)
        sys.exit(1)

    console = Console()
    storage = Storage()

    console.print("[bold blue]spent[/] live dashboard (Ctrl+C to exit)\n")

    try:
        with Live(console=console, refresh_per_second=2) as live:
            while True:
                records = storage.get_today()
                table = _build_live_table(records)
                live.update(table)
                time.sleep(0.5)
    except KeyboardInterrupt:
        console.print("\n[dim]Dashboard stopped.[/]")


def _build_live_table(records: list[dict]):
    from rich.table import Table
    from rich.panel import Panel

    total_cost = sum(r["cost"] for r in records)
    total_tokens = sum(r["input_tokens"] + r["output_tokens"] for r in records)

    by_model: dict[str, dict] = {}
    for r in records:
        model = r["model"]
        if model not in by_model:
            by_model[model] = {"cost": 0.0, "calls": 0, "tokens": 0}
        by_model[model]["cost"] += r["cost"]
        by_model[model]["calls"] += 1
        by_model[model]["tokens"] += r["input_tokens"] + r["output_tokens"]

    table = Table(
        title=f"[bold]Today: ${total_cost:.4f}[/] | {len(records)} calls | {total_tokens:,} tokens",
        show_header=True,
        header_style="bold cyan",
    )
    table.add_column("Model")
    table.add_column("Calls", justify="right")
    table.add_column("Tokens", justify="right")
    table.add_column("Cost", justify="right", style="bold")

    for model, info in sorted(by_model.items(), key=lambda x: x[1]["cost"], reverse=True):
        table.add_row(
            model,
            str(info["calls"]),
            f"{info['tokens']:,}",
            f"${info['cost']:.4f}",
        )

    if not records:
        table.add_row("[dim]No calls tracked today[/]", "", "", "")

    return table


def _bar(pct: float, width: int = 10) -> str:
    filled = int(pct / 100 * width)
    return "[green]" + "█" * filled + "░" * (width - filled) + "[/]"


def _fmt_duration(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes = int(seconds // 60)
    secs = int(seconds % 60)
    return f"{minutes}m {secs}s"
