"""CLI entry point: spent run / spent dashboard / spent report."""

from __future__ import annotations

import json
import subprocess
import sys

import click

from .dashboard import live_dashboard, print_summary
from .storage import Storage


@click.group(invoke_without_command=True)
@click.pass_context
def main(ctx: click.Context) -> None:
    """spent -- see what your AI really costs."""
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


@main.command()
@click.argument("command", nargs=-1, required=True)
@click.option("--budget", "-b", type=float, default=None, help="Budget alert threshold (USD)")
@click.option("--quiet", "-q", is_flag=True, help="Suppress the cost summary on exit")
@click.option("--tag", "-t", multiple=True, help="Tag this session (e.g. --tag experiment-1)")
def run(command: tuple[str, ...], budget: float | None, quiet: bool, tag: tuple[str, ...]) -> None:
    """Run a command and track all LLM API costs.

    \b
    Examples:
        spent run python app.py
        spent run --budget 5.00 python train.py
        spent run --tag experiment-1 python eval.py
    """
    # Prepare the tracker before importing user code
    from .tracker import Tracker
    from .patches import apply_all

    tracker = Tracker.get()
    tracker.quiet = quiet

    if budget is not None:
        tracker.set_budget(budget)

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
