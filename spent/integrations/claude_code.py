"""Claude Code integration -- statusline, hooks, and session tracking."""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path


SETTINGS_PATH = Path.home() / ".claude" / "settings.json"
BACKUP_PATH = SETTINGS_PATH.with_suffix(".json.spent-backup")


def setup_statusline() -> None:
    """Configure Claude Code to show spent cost in the status bar.

    Adds a statusline command to ~/.claude/settings.json that runs
    ``spent status`` and displays the result.
    """
    settings = _read_settings()

    settings = {**settings, "statusline": {
        "command": "spent status",
        "interval": 10,
        "enabled": True,
    }}

    _write_settings(settings)
    print(f"Claude Code statusline configured at {SETTINGS_PATH}")
    print("Restart Claude Code to see costs in the status bar.")


def setup_hooks() -> None:
    """Configure Claude Code hooks for session-level cost tracking.

    Merges spent hooks into the existing hooks configuration without
    overwriting any pre-existing hooks. Adds:
      - PostToolUse (matcher "*"): track-tool-use.sh  (async, 5s timeout)
      - SessionStart (matcher "*"): session-start.sh  (async, 5s timeout)
      - Stop (matcher "*"): session-end.sh             (async, 10s timeout)

    Creates a backup of settings.json before modifying it.
    """
    # Create backup before modifying settings.
    _create_backup()

    settings = _read_settings()
    hooks = dict(settings.get("hooks", {}))

    # Resolve paths to the hook scripts bundled with spent.
    hooks_dir = _find_hooks_dir()
    if hooks_dir is None:
        print(
            "Error: could not locate spent hook scripts. "
            "Ensure spent is installed correctly.",
            file=sys.stderr,
        )
        return

    # Use POSIX paths in commands (Git Bash on Windows needs forward slashes)
    track_script = (hooks_dir / "track-tool-use.sh").as_posix()
    start_script = (hooks_dir / "session-start.sh").as_posix()
    end_script = (hooks_dir / "session-end.sh").as_posix()

    # PostToolUse -- track every tool invocation.
    hooks = _merge_hook(
        hooks,
        hook_type="PostToolUse",
        matcher="*",
        command=f'bash "{track_script}"',
        timeout=5,
        is_async=True,
        tag="spent:track-tool-use",
    )

    # SessionStart -- mark session begin.
    hooks = _merge_hook(
        hooks,
        hook_type="SessionStart",
        matcher="*",
        command=f'bash "{start_script}"',
        timeout=5,
        is_async=True,
        tag="spent:session-start",
    )

    # Stop -- mark session end and show summary.
    hooks = _merge_hook(
        hooks,
        hook_type="Stop",
        matcher="*",
        command=f'bash "{end_script}"',
        timeout=10,
        is_async=True,
        tag="spent:session-end",
    )

    updated_settings = {**settings, "hooks": hooks}
    _write_settings(updated_settings)

    # Show what was installed.
    _print_setup_summary(track_script, start_script, end_script)


def remove_hooks() -> list[str]:
    """Remove all spent-related hooks and statusline from Claude Code settings.

    Returns a list of descriptions of what was removed.
    """
    settings = _read_settings()
    if not settings:
        return []

    removed: list[str] = []

    # Remove hooks that contain "spent" in the command string.
    hooks = settings.get("hooks", {})
    if hooks:
        cleaned_hooks = {}
        for hook_type, entries in hooks.items():
            if not isinstance(entries, list):
                cleaned_hooks[hook_type] = entries
                continue
            kept_entries = []
            for entry in entries:
                entry_hooks = entry.get("hooks", [])
                has_spent = any(
                    "spent" in h.get("command", "")
                    for h in entry_hooks
                    if isinstance(h, dict)
                )
                if has_spent:
                    for h in entry_hooks:
                        cmd = h.get("command", "")
                        if "spent" in cmd:
                            removed.append(f"Hook {hook_type}: {cmd}")
                else:
                    kept_entries.append(entry)
            if kept_entries:
                cleaned_hooks[hook_type] = kept_entries
        settings = {**settings, "hooks": cleaned_hooks}

    # Remove statusline if it references "spent".
    statusline = settings.get("statusline", {})
    if isinstance(statusline, dict):
        cmd = statusline.get("command", "")
        if "spent" in cmd:
            removed.append(f"Statusline: {cmd}")
            settings = {k: v for k, v in settings.items() if k != "statusline"}

    if removed:
        _write_settings(settings)

    return removed


def restore_backup() -> bool:
    """Restore settings.json from the spent backup.

    Returns True if restored, False if no backup found.
    """
    if not BACKUP_PATH.exists():
        return False
    shutil.copy2(str(BACKUP_PATH), str(SETTINGS_PATH))
    return True


def setup() -> None:
    """Full setup: statusline + hooks."""
    setup_statusline()
    print()
    setup_hooks()
    print("\nDone! Restart Claude Code to activate session tracking.")


# -- Internal helpers --------------------------------------------------------


def _create_backup() -> None:
    """Back up settings.json before modifying it."""
    if SETTINGS_PATH.exists():
        shutil.copy2(str(SETTINGS_PATH), str(BACKUP_PATH))
        print(f"Backup saved to {BACKUP_PATH}")


def _read_settings() -> dict:
    """Read ~/.claude/settings.json, returning {} if absent."""
    if SETTINGS_PATH.exists():
        try:
            return json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def _write_settings(settings: dict) -> None:
    """Write settings back to ~/.claude/settings.json."""
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_PATH.write_text(
        json.dumps(settings, indent=2) + "\n",
        encoding="utf-8",
    )


def _find_hooks_dir() -> Path | None:
    """Locate the spent/hooks/ directory.

    Tries the installed package location first, then falls back to a
    development checkout.
    """
    # Relative to this file: ../hooks/
    pkg_hooks = Path(__file__).resolve().parent.parent / "hooks"
    if pkg_hooks.is_dir():
        return pkg_hooks

    # Check for pip-installed editable location.
    import spent
    spent_root = Path(spent.__file__).resolve().parent
    candidate = spent_root / "hooks"
    if candidate.is_dir():
        return candidate

    return None


def _merge_hook(
    hooks: dict,
    *,
    hook_type: str,
    matcher: str,
    command: str,
    timeout: int,
    is_async: bool,
    tag: str,
) -> dict:
    """Add a hook entry to the hooks dict, avoiding duplicates.

    Uses a tag string embedded in the command to detect whether the hook
    is already present. Returns a new dict (no mutation).
    """
    existing_list = list(hooks.get(hook_type, []))

    # Check if a spent hook with this tag already exists.
    for entry in existing_list:
        for h in entry.get("hooks", []):
            if tag in h.get("command", ""):
                # Already installed -- nothing to do.
                return hooks

    # Also check if the script path already appears (handles upgrades).
    for entry in existing_list:
        for h in entry.get("hooks", []):
            if command in h.get("command", ""):
                return hooks

    new_entry = {
        "matcher": matcher,
        "hooks": [
            {
                "type": "command",
                "command": command,
                "timeout": timeout,
                "async": is_async,
            }
        ],
    }

    updated_list = [*existing_list, new_entry]
    return {**hooks, hook_type: updated_list}


def _print_setup_summary(
    track_script: str, start_script: str, end_script: str
) -> None:
    """Print a summary of what was installed."""
    try:
        from rich.console import Console
        from rich.panel import Panel

        console = Console()

        hooks_text = (
            f"[bold]PostToolUse[/]   -> {track_script}\n"
            f"[bold]SessionStart[/]  -> {start_script}\n"
            f"[bold]Stop[/]          -> {end_script}"
        )
        console.print(Panel(hooks_text, title="[bold green]Hooks installed[/]", border_style="green"))

        next_steps = (
            "[bold]1.[/] Restart Claude Code\n"
            "[bold]2.[/] Open a side terminal: [cyan]spent cc live[/]\n"
            "[bold]3.[/] Work normally -- costs appear in real-time"
        )
        console.print(Panel(next_steps, title="[bold blue]Next steps[/]", border_style="blue"))
    except ImportError:
        print("Claude Code hooks configured for spent session tracking.")
        print(f"  PostToolUse  -> {track_script}")
        print(f"  SessionStart -> {start_script}")
        print(f"  Stop         -> {end_script}")
        print()
        print("Next steps:")
        print("  1. Restart Claude Code")
        print("  2. Open a side terminal: spent cc live")
        print("  3. Work normally -- costs appear in real-time")
