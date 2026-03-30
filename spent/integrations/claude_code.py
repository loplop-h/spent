"""Claude Code integration -- statusline, hooks, and session tracking."""

from __future__ import annotations

import json
import sys
from pathlib import Path


SETTINGS_PATH = Path.home() / ".claude" / "settings.json"


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
    """
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

    print("Claude Code hooks configured for spent session tracking.")
    print(f"  PostToolUse  -> {track_script}")
    print(f"  SessionStart -> {start_script}")
    print(f"  Stop         -> {end_script}")


def setup() -> None:
    """Full setup: statusline + hooks."""
    setup_statusline()
    print()
    setup_hooks()
    print("\nDone! Restart Claude Code to activate session tracking.")


# -- Internal helpers --------------------------------------------------------


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
