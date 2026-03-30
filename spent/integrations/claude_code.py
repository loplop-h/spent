"""Claude Code integration -- statusline and hooks."""

from __future__ import annotations

import json
from pathlib import Path


def setup_statusline() -> None:
    """Configure Claude Code to show spent cost in the status bar.

    Adds a statusline command to ~/.claude/settings.json that runs
    `spent status` and displays the result.
    """
    settings_path = Path.home() / ".claude" / "settings.json"

    if settings_path.exists():
        settings = json.loads(settings_path.read_text())
    else:
        settings_path.parent.mkdir(parents=True, exist_ok=True)
        settings = {}

    # Add statusline
    settings["statusline"] = {
        "command": "spent status",
        "interval": 10,
        "enabled": True,
    }

    settings_path.write_text(json.dumps(settings, indent=2))
    print(f"Claude Code statusline configured at {settings_path}")
    print("Restart Claude Code to see costs in the status bar.")


def setup_hooks() -> None:
    """Configure Claude Code hooks to track API calls with spent."""
    settings_path = Path.home() / ".claude" / "settings.json"

    if settings_path.exists():
        settings = json.loads(settings_path.read_text())
    else:
        settings_path.parent.mkdir(parents=True, exist_ok=True)
        settings = {}

    # Add post-tool hook for tracking
    hooks = settings.get("hooks", {})
    hooks["postToolUse"] = hooks.get("postToolUse", [])

    # Check if spent hook already exists
    spent_hooks = [h for h in hooks["postToolUse"] if "spent" in h.get("command", "")]
    if not spent_hooks:
        hooks["postToolUse"].append({
            "command": "spent status",
            "event": "postToolUse",
            "description": "Show spent cost status after tool use",
        })

    settings["hooks"] = hooks
    settings_path.write_text(json.dumps(settings, indent=2))
    print("Claude Code hooks configured for spent tracking.")
