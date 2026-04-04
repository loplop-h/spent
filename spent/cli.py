"""CLI entry point: spent run / spent dashboard / spent report."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import click

from .dashboard import live_dashboard, print_summary
from .storage import Storage


@click.group(invoke_without_command=True)
@click.pass_context
def main(ctx: click.Context) -> None:
    """spent -- Claude Code session cost tracker."""
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


# ─── Claude Code commands ─────────────────────────────────────────────

@main.group()
def cc() -> None:
    """Claude Code session tracking."""
    pass


@cc.command("status")
def cc_status() -> None:
    """Show current Claude Code session costs."""
    from .claude_tracker import ClaudeTracker
    tracker = ClaudeTracker()
    session = tracker.get_current_session()

    if not session or session["tool_uses"] == 0:
        click.echo("No session data yet. Run: spent cc setup")
        return

    eff = session.get("efficiency", {})
    total = session["total_cost"]
    productive = eff.get("productive", 0)
    wasted = eff.get("wasted", 0)
    neutral = eff.get("neutral", 0)
    score = int((productive / total * 100) if total > 0 else 100)

    try:
        from rich.console import Console
        from rich.panel import Panel

        console = Console()
        color = "green" if score >= 75 else "yellow" if score >= 50 else "red"

        lines = [
            f"[bold {color}]Efficiency: {score}%[/]",
            f"[bold white]Cost:[/] ${total:.4f}",
            f"[bold white]Tools:[/] {session['tool_uses']} uses ({session['duration_minutes']:.0f}m)",
            "",
            f"[green]Productive:[/] ${productive:.4f} ({productive/total*100:.0f}%)" if total > 0 else "[green]Productive:[/] $0.00",
            f"[dim]Neutral:[/]    ${neutral:.4f} ({neutral/total*100:.0f}%)" if total > 0 else "[dim]Neutral:[/]    $0.00",
            f"[red]Wasted:[/]     ${wasted:.4f} ({wasted/total*100:.0f}%)" if total > 0 else "[red]Wasted:[/]     $0.00",
        ]
        console.print(Panel("\n".join(lines), title="[bold]spent[/]", border_style="blue"))
    except ImportError:
        click.echo(f"Efficiency: {score}%")
        click.echo(f"Cost: ${total:.4f}")
        click.echo(f"Tools: {session['tool_uses']} uses")


@cc.command("score")
def cc_score() -> None:
    """Show efficiency score for current session."""
    from .claude_tracker import ClaudeTracker
    tracker = ClaudeTracker()
    session = tracker.get_current_session()
    if not session or session["tool_uses"] == 0:
        click.echo("No session data.")
        return
    eff = session.get("efficiency", {})
    total = session["total_cost"]
    productive = eff.get("productive", 0)
    score = int((productive / total * 100) if total > 0 else 100)
    click.echo(f"Efficiency: {score}%")


@cc.command("on")
def cc_on() -> None:
    """Enable session tracking."""
    from pathlib import Path
    flag = Path.home() / ".spent" / "tracking_enabled"
    flag.parent.mkdir(parents=True, exist_ok=True)
    flag.write_text("1")
    click.echo("Tracking ON. Every tool use is now being logged.")


@cc.command("off")
def cc_off() -> None:
    """Disable session tracking."""
    from pathlib import Path
    flag = Path.home() / ".spent" / "tracking_enabled"
    if flag.exists():
        flag.write_text("0")
    click.echo("Tracking OFF.")


@cc.command("live")
def cc_live() -> None:
    """Live terminal dashboard (keep open in a side pane).

    \b
    Split your terminal and run:
        spent cc live
    """
    from .tui import run_tui
    run_tui()


@cc.command("dashboard")
@click.option("--port", "-p", default=5050, help="Port (default: 5050)")
def cc_dashboard(port: int) -> None:
    """Open the Claude Code dashboard in your browser."""
    from .claude_web import serve
    serve(port=port, open_browser=True)


@cc.command("history")
@click.option("--days", "-d", default=7, help="Number of days (default: 7)")
def cc_history(days: int) -> None:
    """Show past session history."""
    from .claude_tracker import ClaudeTracker
    tracker = ClaudeTracker()
    sessions = tracker.get_session_history(days=days)

    if not sessions:
        click.echo("No session history yet.")
        return

    try:
        from rich.console import Console
        from rich.table import Table

        console = Console()
        table = Table(title=f"Sessions (last {days} days)", show_header=True, header_style="bold cyan")
        table.add_column("Date")
        table.add_column("Duration", justify="right")
        table.add_column("Tools", justify="right")
        table.add_column("Cost", justify="right", style="bold")
        table.add_column("Efficiency", justify="right")

        for s in sessions:
            score = tracker.get_efficiency_score(s)
            color = "green" if score >= 75 else "yellow" if score >= 50 else "red"
            table.add_row(
                s.get("date", "?"),
                f"{s.get('duration_minutes', 0):.0f}m",
                str(s.get("tool_uses", 0)),
                f"${s.get('total_cost', 0):.4f}",
                f"[{color}]{score:.0f}%[/]",
            )
        console.print(table)
    except ImportError:
        for s in sessions:
            score = tracker.get_efficiency_score(s)
            click.echo(f"{s.get('date', '?')} | {s.get('tool_uses', 0)} tools | ${s.get('total_cost', 0):.4f} | {score:.0f}%")


@cc.command("compact")
@click.option("--days", "-d", default=30, help="Keep events from the last N days (default: 30)")
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation prompt")
def cc_compact(days: int, yes: bool) -> None:
    """Compact the JSONL log file, keeping only recent events."""
    from .claude_tracker import ClaudeTracker
    tracker = ClaudeTracker()
    log_path = tracker._log_path

    if not log_path.exists():
        click.echo("No log file to compact.")
        return

    from datetime import datetime, timedelta, timezone

    before_size = log_path.stat().st_size
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    cutoff_str = cutoff.strftime("%Y-%m-%dT%H:%M:%S")

    # Read all lines and filter.
    kept_lines: list[str] = []
    total_lines = 0
    with open(log_path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            stripped = line.strip()
            if not stripped:
                continue
            total_lines += 1
            try:
                data = json.loads(stripped)
                ts = data.get("ts", "")
                if ts >= cutoff_str:
                    kept_lines.append(stripped)
            except (json.JSONDecodeError, TypeError):
                pass

    removed = total_lines - len(kept_lines)
    click.echo(f"Log file: {log_path}")
    click.echo(f"  Before: {before_size:,} bytes, {total_lines} events")
    click.echo(f"  After:  {len(kept_lines)} events (removing {removed} older than {days} days)")

    if removed == 0:
        click.echo("Nothing to compact.")
        return

    if not yes:
        if not click.confirm("Proceed with compaction?"):
            click.echo("Aborted.")
            return

    # Write atomically: write to .tmp, then rename.
    tmp_path = log_path.with_suffix(".jsonl.tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        for line in kept_lines:
            f.write(line + "\n")

    # Atomic rename (works on same filesystem).
    import os
    if sys.platform == "win32":
        # Windows doesn't support atomic rename over existing file.
        os.replace(str(tmp_path), str(log_path))
    else:
        os.replace(str(tmp_path), str(log_path))

    after_size = log_path.stat().st_size
    click.echo(f"Compacted: {before_size:,} -> {after_size:,} bytes ({removed} events removed)")

    # Clean up old model files.
    import time as _time
    models_dir = Path.home() / ".spent" / "models"
    if models_dir.exists():
        cutoff_time = _time.time() - (days * 86400)
        cleaned = 0
        for model_file in models_dir.iterdir():
            try:
                if model_file.stat().st_mtime < cutoff_time:
                    model_file.unlink()
                    cleaned += 1
            except OSError:
                pass
        if cleaned:
            click.echo(f"Cleaned {cleaned} old model files")


@cc.command("export")
@click.option("--project", "-p", default=None, help="Filter by project name")
@click.option("--output", "-o", "output_path", default=None, type=click.Path(), help="Output file path")
@click.option("--format", "fmt", type=click.Choice(["sqlite", "csv", "json"]), default="sqlite", help="Export format")
def cc_export(project: str | None, output_path: str | None, fmt: str) -> None:
    """Export Claude Code session data to SQLite, CSV, or JSON.

    \b
    Examples:
        spent cc export                           # Import JSONL into SQLite
        spent cc export --format csv -o costs.csv # CSV export
        spent cc export --format json             # JSON to stdout
        spent cc export --project myapp           # Filter by project
    """
    from .storage import ClaudeStorage

    store = ClaudeStorage()

    # Always import latest JSONL data first.
    imported = store.import_from_jsonl(project=project)
    if imported:
        click.echo(f"Imported {imported} new events into SQLite")

    if fmt == "sqlite":
        click.echo(f"SQLite database: {store.db_path}")
        sessions = store.get_sessions(project=project)
        click.echo(f"Sessions: {len(sessions)}")
        breakdown = store.get_model_breakdown(project=project)
        if breakdown:
            click.echo("Model breakdown:")
            for row in breakdown:
                click.echo(
                    f"  {row['model']:>8}  "
                    f"{row['events']} events  "
                    f"${row['total_cost']:.4f}"
                )

    elif fmt == "csv":
        out = Path(output_path) if output_path else Path("spent-export.csv")
        count = store.export_csv(out, project=project)
        click.echo(f"Exported {count} events to {out}")

    elif fmt == "json":
        sessions = store.get_sessions(project=project)
        breakdown = store.get_model_breakdown(project=project)
        result = {
            "sessions": sessions,
            "model_breakdown": breakdown,
        }
        output = json.dumps(result, indent=2, default=str)
        if output_path:
            Path(output_path).write_text(output, encoding="utf-8")
            click.echo(f"Exported to {output_path}")
        else:
            click.echo(output)


@cc.command("uninstall")
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation prompts")
def cc_uninstall(yes: bool) -> None:
    """Remove spent hooks from Claude Code and optionally delete data."""
    from .integrations.claude_code import remove_hooks, SETTINGS_PATH

    removed = remove_hooks()
    if removed:
        click.echo("Removed from Claude Code settings:")
        for item in removed:
            click.echo(f"  - {item}")
    else:
        click.echo("No spent hooks found in Claude Code settings.")

    # Offer to delete data directory.
    data_dir = Path.home() / ".spent"
    if data_dir.exists():
        if yes or click.confirm(f"\nDelete data directory ({data_dir})?", default=False):
            import shutil
            shutil.rmtree(data_dir)
            click.echo(f"Deleted {data_dir}")
        else:
            click.echo(f"Data directory kept at {data_dir}")

    # Offer to restore backup.
    backup_path = SETTINGS_PATH.with_suffix(".json.spent-backup")
    if backup_path.exists():
        if yes or click.confirm(f"\nRestore settings from backup ({backup_path})?", default=False):
            import shutil
            shutil.copy2(str(backup_path), str(SETTINGS_PATH))
            click.echo(f"Restored {SETTINGS_PATH} from backup.")


@cc.command("setup")
@click.option("--restore", is_flag=True, help="Restore settings from backup")
def cc_setup(restore: bool) -> None:
    """Configure Claude Code hooks for automatic tracking."""
    from .integrations.claude_code import setup_hooks, restore_backup

    if restore:
        restored = restore_backup()
        if restored:
            click.echo("Settings restored from backup. Restart Claude Code.")
        else:
            click.echo("No backup found to restore.")
        return

    setup_hooks()
    click.echo("Done! Tracking hooks installed. Restart Claude Code to activate.")


@cc.command("tips")
def cc_tips() -> None:
    """Show efficiency tips for current session."""
    from .claude_tracker import ClaudeTracker
    tracker = ClaudeTracker()
    session = tracker.get_current_session()

    if not session or session["tool_uses"] == 0:
        click.echo("No session data to analyze.")
        return

    tips = session.get("tips", [])
    if not tips:
        click.echo("No tips -- you're being efficient!")
        return

    for i, tip in enumerate(tips, 1):
        click.echo(f"  {i}. {tip}")


# ─── Legacy / generic commands ────────────────────────────────────────

@main.command()
@click.argument("command", nargs=-1, required=True)
@click.option("--budget", "-b", type=float, default=None, help="Budget alert threshold (USD)")
@click.option("--quiet", "-q", is_flag=True, help="Suppress the cost summary on exit")
@click.option("--tag", "-t", multiple=True, help="Tag this session (e.g. --tag experiment-1)")
@click.option("--optimize", "-o", is_flag=True, help="Auto-route simple tasks to cheaper models")
def run(command: tuple[str, ...], budget: float | None, quiet: bool, tag: tuple[str, ...], optimize: bool) -> None:
    """Run a command and track all LLM API costs.

    \b
    Examples:
        spent run python app.py
        spent run --budget 5.00 python train.py
        spent run --optimize python app.py    # auto-route to cheaper models
        spent run --tag experiment-1 python eval.py
    """
    # Prepare the tracker before importing user code
    from .tracker import Tracker
    from .patches import apply_all
    from .router import Router

    tracker = Tracker.get()
    tracker.quiet = quiet

    if budget is not None:
        tracker.set_budget(budget)

    router = Router.get()
    router.enabled = optimize

    # Apply patches to intercept SDK calls
    apply_all()

    # Determine if we're running a Python script or arbitrary command
    cmd_list = list(command)

    if cmd_list[0] == "python" or cmd_list[0] == "python3":
        # Run Python script in the same process for patch visibility
        _run_python_inprocess(cmd_list[1:])
    else:
        # Run as subprocess (patches won't apply -- use SPENT_ENABLED=1 in code)
        result = subprocess.run(cmd_list)
        sys.exit(result.returncode)


@main.command()
def dashboard() -> None:
    """Live cost dashboard (updates in real-time)."""
    live_dashboard()


@main.command()
@click.option("--port", "-p", default=5050, help="Port number (default: 5050)")
@click.option("--no-open", is_flag=True, help="Don't auto-open browser")
def web(port: int, no_open: bool) -> None:
    """Open the web dashboard in your browser.

    \b
    Beautiful charts showing costs, models, savings, and forecasts.
        spent web              # opens at http://localhost:5050
        spent web --port 8080  # custom port
    """
    from .web import run_server
    run_server(port=port, open_browser=not no_open)


@main.command()
@click.option("--compact", "-c", is_flag=True, help="Single-line mode (for status bars)")
@click.option("--interval", "-i", default=1.0, help="Update interval in seconds")
def ticker(compact: bool, interval: float) -> None:
    """Live cost ticker (real-time, runs alongside your tools).

    \b
    Run in a split terminal pane next to Claude Code, Cursor, etc:
        spent ticker              # compact widget
        spent ticker --compact    # single-line mode for status bars
    """
    from .ticker import run_ticker
    run_ticker(compact=compact, interval=interval)


@main.command()
@click.option("--interval", "-i", default=2.0, help="Update interval in seconds")
def panel(interval: float) -> None:
    """Live cost panel widget (compact, for side panes).

    \b
    Perfect for a narrow terminal pane:
        spent panel
    """
    from .ticker import run_panel
    run_panel(interval=interval)


@main.command()
def status() -> None:
    """Print a single-line cost status (for scripts and integrations)."""
    from .ticker import get_statusline
    click.echo(get_statusline())


@main.command()
@click.option("--session", "-s", default=None, help="Show specific session")
@click.option("--today", is_flag=True, help="Show today's costs")
@click.option("--json-output", "--json", "as_json", is_flag=True, help="Output as JSON")
@click.option("--csv", "as_csv", is_flag=True, help="Output as CSV")
@click.option("--limit", "-n", default=20, help="Number of sessions to show")
def report(
    session: str | None,
    today: bool,
    as_json: bool,
    as_csv: bool,
    limit: int,
) -> None:
    """Show cost reports.

    \b
    Examples:
        spent report                  # Recent sessions
        spent report --today          # Today's breakdown
        spent report --json           # Machine-readable output
        spent report -s abc12345      # Specific session
    """
    storage = Storage()

    if session:
        records = storage.get_session(session)
        if not records:
            click.echo(f"No records found for session {session}")
            return
        _output_records(records, as_json, as_csv)

    elif today:
        records = storage.get_today()
        if not records:
            click.echo("No API calls tracked today.")
            return
        _output_records(records, as_json, as_csv)

    else:
        sessions = storage.get_sessions(limit=limit)
        if not sessions:
            click.echo("No sessions recorded yet. Run: spent run python your_script.py")
            return

        if as_json:
            click.echo(json.dumps(sessions, indent=2, default=str))
            return

        # Pretty table
        try:
            from rich.console import Console
            from rich.table import Table

            console = Console()
            table = Table(title="Recent Sessions", show_header=True, header_style="bold cyan")
            table.add_column("Session", style="dim")
            table.add_column("Started")
            table.add_column("Calls", justify="right")
            table.add_column("Tokens", justify="right")
            table.add_column("Cost", justify="right", style="bold")

            for s in sessions:
                table.add_row(
                    s["session_id"],
                    s["started"][:19],
                    str(s["calls"]),
                    f"{(s['total_input'] or 0) + (s['total_output'] or 0):,}",
                    f"${s['total_cost']:.4f}",
                )
            console.print(table)
            total = sum(s["total_cost"] for s in sessions)
            console.print(f"\n[bold]Total across sessions: ${total:.4f}[/]")

        except ImportError:
            for s in sessions:
                tokens = (s["total_input"] or 0) + (s["total_output"] or 0)
                click.echo(
                    f"{s['session_id']}  {s['started'][:19]}  "
                    f"{s['calls']} calls  {tokens:,} tokens  ${s['total_cost']:.4f}"
                )


@main.group()
def setup() -> None:
    """Set up integrations with AI coding tools."""
    pass


@setup.command("claude-code")
def setup_claude_code() -> None:
    """Integrate spent with Claude Code (statusline + hooks).

    \b
    Adds a cost ticker to Claude Code's status bar and
    configures hooks for session-level cost tracking.
        spent setup claude-code
    """
    from .integrations.claude_code import setup
    setup()


@main.command()
@click.option("--today", is_flag=True, help="Show all sessions from today")
@click.option("--days", "-d", default=7, help="Number of days of history (default: 7)")
@click.option("--json-output", "--json", "as_json", is_flag=True, help="Output as JSON")
def session(today: bool, days: int, as_json: bool) -> None:
    """Show Claude Code session costs and efficiency.

    \b
    Examples:
        spent session              # Current / most recent session
        spent session --today      # All sessions from today
        spent session --days 30    # Last 30 days of sessions
        spent session --json       # Machine-readable output
    """
    from .claude_tracker import ClaudeTracker

    tracker = ClaudeTracker()

    if today:
        sessions = tracker.get_today_sessions()
        if not sessions:
            click.echo("No Claude Code sessions tracked today.")
            return
        if as_json:
            click.echo(json.dumps(sessions, indent=2, default=str))
            return
        _print_session_list(sessions, tracker)

    elif days != 7 or not sys.stdin.isatty():
        # Explicit --days flag or piped output: show history.
        sessions = tracker.get_session_history(days=days)
        if not sessions:
            click.echo(f"No Claude Code sessions in the last {days} days.")
            return
        if as_json:
            click.echo(json.dumps(sessions, indent=2, default=str))
            return
        _print_session_list(sessions, tracker)

    else:
        # Default: show current session.
        data = tracker.get_current_session()
        if not data.get("session_id"):
            click.echo(
                "No Claude Code sessions recorded yet.\n"
                "Run: spent setup claude-code"
            )
            return
        if as_json:
            click.echo(json.dumps(data, indent=2, default=str))
            return
        _print_session_detail(data, tracker)


def _print_session_detail(data: dict, tracker) -> None:
    """Pretty-print a single session's metrics."""
    score = tracker.get_efficiency_score(data)
    eff = data.get("efficiency", {})

    try:
        from rich.console import Console
        from rich.panel import Panel
        from rich.table import Table

        console = Console()

        # Header.
        score_color = "green" if score >= 70 else "yellow" if score >= 40 else "red"
        header = (
            f"[bold white]Session:[/]     [dim]{data['session_id']}[/]\n"
            f"[bold white]Started:[/]     [dim]{data['started'][:19]}[/]\n"
            f"[bold white]Duration:[/]    [dim]{data['duration_minutes']:.1f} min[/]\n"
            f"[bold white]Total Cost:[/]  [bold]${data['total_cost']:.4f}[/]\n"
            f"[bold white]Tool Uses:[/]   [dim]{data['tool_uses']}[/]\n"
            f"[bold white]Tokens:[/]      [dim]{data['total_tokens']:,}[/]\n"
            f"[bold white]Efficiency:[/]  [{score_color}]{score:.0f}/100[/]"
        )
        console.print(Panel(header, title="[bold]spent session[/]", border_style="blue"))

        # Efficiency breakdown.
        p = eff.get("productive", 0)
        w = eff.get("wasted", 0)
        n = eff.get("neutral", 0)
        console.print(
            f"  [green]Productive: ${p:.4f}[/]  "
            f"[dim]Neutral: ${n:.4f}[/]  "
            f"[red]Wasted: ${w:.4f}[/]"
        )
        console.print()

        # Tool breakdown table.
        by_tool = data.get("by_tool", {})
        if by_tool:
            table = Table(show_header=True, header_style="bold cyan", box=None, padding=(0, 2))
            table.add_column("Tool", style="white")
            table.add_column("Uses", justify="right", style="dim")
            table.add_column("Cost", justify="right", style="bold")
            for tool_name, info in by_tool.items():
                table.add_row(tool_name, str(info["count"]), f"${info['cost']:.4f}")
            console.print(table)

    except ImportError:
        click.echo(f"Session: {data['session_id']}")
        click.echo(f"Started: {data['started'][:19]}")
        click.echo(f"Duration: {data['duration_minutes']:.1f} min")
        click.echo(f"Cost: ${data['total_cost']:.4f}")
        click.echo(f"Tool uses: {data['tool_uses']}")
        click.echo(f"Efficiency: {score:.0f}/100")
        click.echo(
            f"  Productive: ${eff.get('productive', 0):.4f}  "
            f"Neutral: ${eff.get('neutral', 0):.4f}  "
            f"Wasted: ${eff.get('wasted', 0):.4f}"
        )
        for tool_name, info in data.get("by_tool", {}).items():
            click.echo(f"  {tool_name}: {info['count']} uses, ${info['cost']:.4f}")


def _print_session_list(sessions: list[dict], tracker) -> None:
    """Pretty-print a list of session summaries."""
    try:
        from rich.console import Console
        from rich.table import Table

        console = Console()
        table = Table(
            title="Claude Code Sessions",
            show_header=True,
            header_style="bold cyan",
        )
        table.add_column("Session", style="dim")
        table.add_column("Started")
        table.add_column("Duration", justify="right")
        table.add_column("Tools", justify="right")
        table.add_column("Cost", justify="right", style="bold")
        table.add_column("Score", justify="right")

        total_cost = 0.0
        for s in sessions:
            score = tracker.get_efficiency_score(s)
            score_color = "green" if score >= 70 else "yellow" if score >= 40 else "red"
            table.add_row(
                s["session_id"],
                s["started"][:19],
                f"{s['duration_minutes']:.0f}m",
                str(s["tool_uses"]),
                f"${s['total_cost']:.4f}",
                f"[{score_color}]{score:.0f}[/]",
            )
            total_cost += s["total_cost"]

        console.print(table)
        console.print(f"\n[bold]Total: ${total_cost:.4f} across {len(sessions)} sessions[/]")

    except ImportError:
        for s in sessions:
            score = tracker.get_efficiency_score(s)
            click.echo(
                f"{s['session_id']}  {s['started'][:19]}  "
                f"{s['duration_minutes']:.0f}m  {s['tool_uses']} tools  "
                f"${s['total_cost']:.4f}  score:{score:.0f}"
            )


@main.command()
def reset() -> None:
    """Delete all tracked data."""
    from pathlib import Path
    db_path = Path.home() / ".spent" / "data.db"
    if db_path.exists():
        if click.confirm("Delete all spent tracking data?"):
            db_path.unlink()
            click.echo("Data cleared.")
    else:
        click.echo("No data to clear.")


def _run_python_inprocess(args: list[str]) -> None:
    """Run a Python script in the current process so patches work."""
    import runpy

    if not args:
        click.echo("Usage: spent run python <script.py> [args...]")
        sys.exit(1)

    script = args[0]
    sys.argv = args  # Set argv so the script sees its own args

    try:
        runpy.run_path(script, run_name="__main__")
    except SystemExit as e:
        sys.exit(e.code)
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


def _output_records(records: list[dict], as_json: bool, as_csv: bool) -> None:
    if as_json:
        click.echo(json.dumps(records, indent=2, default=str))
    elif as_csv:
        if records:
            headers = list(records[0].keys())
            click.echo(",".join(headers))
            for r in records:
                click.echo(",".join(str(r.get(h, "")) for h in headers))
    else:
        total_cost = sum(r["cost"] for r in records)
        total_tokens = sum(r["input_tokens"] + r["output_tokens"] for r in records)

        try:
            from rich.console import Console
            console = Console()
            console.print(f"[bold]{len(records)} calls[/] | {total_tokens:,} tokens | [bold]${total_cost:.4f}[/]\n")
            for r in records:
                tokens = r["input_tokens"] + r["output_tokens"]
                console.print(
                    f"  [dim]{r['timestamp'][:19]}[/]  {r['model']:30s}  "
                    f"{tokens:>8,} tok  [bold]${r['cost']:.4f}[/]"
                )
        except ImportError:
            click.echo(f"{len(records)} calls | {total_tokens:,} tokens | ${total_cost:.4f}")
            for r in records:
                click.echo(f"  {r['timestamp'][:19]}  {r['model']}  ${r['cost']:.4f}")
