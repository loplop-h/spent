"""Tests for Claude Code integration: setup, uninstall, backup/restore."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from spent.integrations.claude_code import (
    BACKUP_PATH,
    SETTINGS_PATH,
    _merge_hook,
    remove_hooks,
    restore_backup,
    setup_hooks,
)


@pytest.fixture()
def fake_home(tmp_path: Path):
    """Redirect SETTINGS_PATH and BACKUP_PATH to a temp directory."""
    fake_claude_dir = tmp_path / ".claude"
    fake_claude_dir.mkdir()
    fake_settings = fake_claude_dir / "settings.json"
    fake_backup = fake_claude_dir / "settings.json.spent-backup"

    with (
        patch("spent.integrations.claude_code.SETTINGS_PATH", fake_settings),
        patch("spent.integrations.claude_code.BACKUP_PATH", fake_backup),
    ):
        yield {
            "settings": fake_settings,
            "backup": fake_backup,
            "claude_dir": fake_claude_dir,
        }


@pytest.fixture()
def fake_hooks_dir(tmp_path: Path):
    """Create a fake hooks directory with dummy scripts."""
    hooks = tmp_path / "hooks"
    hooks.mkdir()
    (hooks / "track-tool-use.sh").write_text("#!/bin/bash\n")
    (hooks / "session-start.sh").write_text("#!/bin/bash\n")
    (hooks / "session-end.sh").write_text("#!/bin/bash\n")
    return hooks


def _write_settings(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def _read_settings(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


# ── setup_hooks on empty settings ────────────────────────────────

class TestSetupHooksEmpty:
    def test_creates_hooks_on_empty_settings(
        self, fake_home: dict, fake_hooks_dir: Path
    ) -> None:
        settings_path = fake_home["settings"]
        _write_settings(settings_path, {})

        with patch(
            "spent.integrations.claude_code._find_hooks_dir",
            return_value=fake_hooks_dir,
        ):
            setup_hooks()

        result = _read_settings(settings_path)
        hooks = result.get("hooks", {})

        # All three hook types should be present.
        assert "PostToolUse" in hooks
        assert "SessionStart" in hooks
        assert "Stop" in hooks

        # Each should have exactly one entry.
        assert len(hooks["PostToolUse"]) == 1
        assert len(hooks["SessionStart"]) == 1
        assert len(hooks["Stop"]) == 1

    def test_creates_hooks_when_no_settings_file(
        self, fake_home: dict, fake_hooks_dir: Path
    ) -> None:
        # Settings file doesn't exist yet.
        settings_path = fake_home["settings"]
        assert not settings_path.exists()

        with patch(
            "spent.integrations.claude_code._find_hooks_dir",
            return_value=fake_hooks_dir,
        ):
            setup_hooks()

        assert settings_path.exists()
        result = _read_settings(settings_path)
        assert "PostToolUse" in result.get("hooks", {})


# ── setup_hooks with existing hooks (merge) ──────────────────────

class TestSetupHooksMerge:
    def test_preserves_existing_hooks(
        self, fake_home: dict, fake_hooks_dir: Path
    ) -> None:
        settings_path = fake_home["settings"]
        existing = {
            "hooks": {
                "PostToolUse": [
                    {
                        "matcher": "*.py",
                        "hooks": [
                            {
                                "type": "command",
                                "command": "ruff check --fix",
                                "timeout": 10,
                            }
                        ],
                    }
                ]
            },
            "some_other_setting": True,
        }
        _write_settings(settings_path, existing)

        with patch(
            "spent.integrations.claude_code._find_hooks_dir",
            return_value=fake_hooks_dir,
        ):
            setup_hooks()

        result = _read_settings(settings_path)
        hooks = result["hooks"]

        # Original hook preserved + spent hook added.
        assert len(hooks["PostToolUse"]) == 2
        commands = [
            h["command"]
            for entry in hooks["PostToolUse"]
            for h in entry.get("hooks", [])
        ]
        assert any("ruff" in c for c in commands)
        assert any("spent" in c or "track-tool-use" in c for c in commands)

        # Other settings preserved.
        assert result["some_other_setting"] is True


# ── Idempotent re-install ─────────────────────────────────────────

class TestSetupIdempotent:
    def test_running_setup_twice_does_not_duplicate(
        self, fake_home: dict, fake_hooks_dir: Path
    ) -> None:
        settings_path = fake_home["settings"]
        _write_settings(settings_path, {})

        with patch(
            "spent.integrations.claude_code._find_hooks_dir",
            return_value=fake_hooks_dir,
        ):
            setup_hooks()
            setup_hooks()

        result = _read_settings(settings_path)
        hooks = result.get("hooks", {})

        # Should still have exactly one entry per hook type.
        assert len(hooks["PostToolUse"]) == 1
        assert len(hooks["SessionStart"]) == 1
        assert len(hooks["Stop"]) == 1


# ── remove_hooks ──────────────────────────────────────────────────

class TestRemoveHooks:
    def test_removes_spent_hooks(
        self, fake_home: dict, fake_hooks_dir: Path
    ) -> None:
        settings_path = fake_home["settings"]
        _write_settings(settings_path, {})

        # Install hooks first.
        with patch(
            "spent.integrations.claude_code._find_hooks_dir",
            return_value=fake_hooks_dir,
        ):
            setup_hooks()

        # Verify hooks exist.
        before = _read_settings(settings_path)
        assert len(before["hooks"]["PostToolUse"]) == 1

        # Remove hooks.
        removed = remove_hooks()

        # Should have removed 3 hooks + nothing else.
        assert len(removed) == 3
        assert all("spent" in r.lower() or "track-tool-use" in r.lower() for r in removed)

        # Settings should have empty hooks.
        after = _read_settings(settings_path)
        hooks = after.get("hooks", {})
        for entries in hooks.values():
            assert len(entries) == 0 if isinstance(entries, list) else True

    def test_removes_only_spent_hooks_preserves_others(
        self, fake_home: dict, fake_hooks_dir: Path
    ) -> None:
        settings_path = fake_home["settings"]
        existing = {
            "hooks": {
                "PostToolUse": [
                    {
                        "matcher": "*.py",
                        "hooks": [
                            {"type": "command", "command": "ruff check", "timeout": 10}
                        ],
                    }
                ]
            }
        }
        _write_settings(settings_path, existing)

        # Install spent hooks.
        with patch(
            "spent.integrations.claude_code._find_hooks_dir",
            return_value=fake_hooks_dir,
        ):
            setup_hooks()

        # Should now have 2 PostToolUse entries.
        mid = _read_settings(settings_path)
        assert len(mid["hooks"]["PostToolUse"]) == 2

        # Remove spent hooks.
        removed = remove_hooks()
        assert len(removed) >= 1

        # Ruff hook should remain.
        after = _read_settings(settings_path)
        post_hooks = after["hooks"].get("PostToolUse", [])
        assert len(post_hooks) == 1
        assert "ruff" in post_hooks[0]["hooks"][0]["command"]

    def test_removes_statusline(self, fake_home: dict) -> None:
        settings_path = fake_home["settings"]
        _write_settings(settings_path, {
            "statusline": {
                "command": "spent status",
                "interval": 10,
                "enabled": True,
            }
        })

        removed = remove_hooks()
        assert any("statusline" in r.lower() for r in removed)

        after = _read_settings(settings_path)
        assert "statusline" not in after

    def test_remove_on_empty_settings(self, fake_home: dict) -> None:
        settings_path = fake_home["settings"]
        _write_settings(settings_path, {})

        removed = remove_hooks()
        assert removed == []

    def test_remove_when_no_file(self, fake_home: dict) -> None:
        # Settings file doesn't exist.
        removed = remove_hooks()
        assert removed == []


# ── Backup during setup ──────────────────────────────────────────

class TestBackup:
    def test_backup_created_during_setup(
        self, fake_home: dict, fake_hooks_dir: Path
    ) -> None:
        settings_path = fake_home["settings"]
        backup_path = fake_home["backup"]

        original = {"existing_key": "original_value"}
        _write_settings(settings_path, original)

        with patch(
            "spent.integrations.claude_code._find_hooks_dir",
            return_value=fake_hooks_dir,
        ):
            setup_hooks()

        # Backup should exist and contain original settings.
        assert backup_path.exists()
        backup_data = _read_settings(backup_path)
        assert backup_data["existing_key"] == "original_value"
        # Backup should NOT have hooks (it was saved before modification).
        assert "hooks" not in backup_data

    def test_no_backup_when_no_settings_file(
        self, fake_home: dict, fake_hooks_dir: Path
    ) -> None:
        backup_path = fake_home["backup"]

        with patch(
            "spent.integrations.claude_code._find_hooks_dir",
            return_value=fake_hooks_dir,
        ):
            setup_hooks()

        # No backup if there was no pre-existing settings file.
        assert not backup_path.exists()


# ── Restore ──────────────────────────────────────────────────────

class TestRestore:
    def test_restore_from_backup(self, fake_home: dict) -> None:
        settings_path = fake_home["settings"]
        backup_path = fake_home["backup"]

        # Write different content to backup and current settings.
        original = {"clean": True}
        modified = {"clean": True, "hooks": {"PostToolUse": [{"matcher": "*"}]}}
        _write_settings(backup_path, original)
        _write_settings(settings_path, modified)

        result = restore_backup()
        assert result is True

        # Settings should now match backup.
        restored = _read_settings(settings_path)
        assert restored == original

    def test_restore_no_backup(self, fake_home: dict) -> None:
        result = restore_backup()
        assert result is False
