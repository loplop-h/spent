"""Tests for the `spent cc` CLI subcommands using Click's CliRunner."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from spent.cli import main


# ── Helpers ────────────────────────────────────────────────────────

def _make_event(
    *,
    tool: str = "Edit",
    ts: str = "2026-03-30T10:00:00",
    session: str = "sess-001",
    model: str = "sonnet",
    event: str = "tool_use",
    input_size: int = 400,
    output_size: int = 200,
    has_error: bool = False,
    file_path: str = "",
    output_text: str = "",
) -> dict[str, Any]:
    return {
        "ts": ts,
        "tool": tool,
        "input_size": input_size,
        "output_size": output_size,
        "session": session,
        "model": model,
        "event": event,
        "has_error": has_error,
        "file_path": file_path,
        "output_text": output_text,
    }


def _session_events(
    count: int = 5,
    start: str = "2026-03-30T10:00:00",
    session_id: str = "sess-001",
) -> list[dict[str, Any]]:
    base = datetime.fromisoformat(start)
    tools = ["Read", "Grep", "Edit", "Write", "Bash"]
    events: list[dict[str, Any]] = []
    for i in range(count):
        ts = (base + timedelta(minutes=i * 2)).isoformat()
        events.append(_make_event(
            tool=tools[i % len(tools)],
            ts=ts,
            session=session_id,
            input_size=400 + i * 100,
            output_size=200 + i * 50,
        ))
    return events


def _write_log(path: Path, events: list[dict]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        for ev in events:
            f.write(json.dumps(ev) + "\n")


@pytest.fixture()
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture()
def log_with_data(tmp_path: Path) -> Path:
    """Create a JSONL log file with session data."""
    log = tmp_path / "sessions.jsonl"
    _write_log(log, _session_events(count=6))
    return log


@pytest.fixture()
def empty_log(tmp_path: Path) -> Path:
    """Create an empty JSONL log file."""
    log = tmp_path / "sessions.jsonl"
    log.write_text("")
    return log


def _patch_tracker_log(log_path: Path):
    """Monkeypatch ClaudeTracker.LOG_PATH so the CLI reads our temp file."""
    return patch("spent.claude_tracker.ClaudeTracker.LOG_PATH", log_path)


# ── cc status ──────────────────────────────────────────────────────

class TestCcStatus:
    def test_status_with_data(
        self, runner: CliRunner, log_with_data: Path
    ) -> None:
        with _patch_tracker_log(log_with_data):
            result = runner.invoke(main, ["cc", "status"])
        assert result.exit_code == 0
        # Output should contain efficiency info (rich or plain).
        output_lower = result.output.lower()
        assert "efficiency" in output_lower or "cost" in output_lower

    def test_status_with_no_data(
        self, runner: CliRunner, empty_log: Path
    ) -> None:
        with _patch_tracker_log(empty_log):
            result = runner.invoke(main, ["cc", "status"])
        assert result.exit_code == 0
        assert "no session data" in result.output.lower()

    def test_status_nonexistent_log(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        with _patch_tracker_log(tmp_path / "nope.jsonl"):
            result = runner.invoke(main, ["cc", "status"])
        assert result.exit_code == 0


# ── cc score ───────────────────────────────────────────────────────

class TestCcScore:
    def test_score_with_data(
        self, runner: CliRunner, log_with_data: Path
    ) -> None:
        with _patch_tracker_log(log_with_data):
            result = runner.invoke(main, ["cc", "score"])
        assert result.exit_code == 0
        assert "%" in result.output

    def test_score_no_data(
        self, runner: CliRunner, empty_log: Path
    ) -> None:
        with _patch_tracker_log(empty_log):
            result = runner.invoke(main, ["cc", "score"])
        assert result.exit_code == 0
        assert "no session data" in result.output.lower()


# ── cc on / cc off ─────────────────────────────────────────────────

class TestCcOnOff:
    def test_on_creates_flag_file(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        flag_path = tmp_path / ".spent" / "tracking_enabled"
        with patch("pathlib.Path.home", return_value=tmp_path):
            result = runner.invoke(main, ["cc", "on"])
        assert result.exit_code == 0
        assert flag_path.exists()
        assert flag_path.read_text() == "1"
        assert "on" in result.output.lower()

    def test_off_writes_zero(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        flag_path = tmp_path / ".spent" / "tracking_enabled"
        flag_path.parent.mkdir(parents=True, exist_ok=True)
        flag_path.write_text("1")

        with patch("pathlib.Path.home", return_value=tmp_path):
            result = runner.invoke(main, ["cc", "off"])
        assert result.exit_code == 0
        assert flag_path.read_text() == "0"
        assert "off" in result.output.lower()

    def test_off_when_no_flag_file(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        with patch("pathlib.Path.home", return_value=tmp_path):
            result = runner.invoke(main, ["cc", "off"])
        assert result.exit_code == 0

    def test_on_idempotent(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        with patch("pathlib.Path.home", return_value=tmp_path):
            runner.invoke(main, ["cc", "on"])
            result = runner.invoke(main, ["cc", "on"])
        assert result.exit_code == 0
        flag_path = tmp_path / ".spent" / "tracking_enabled"
        assert flag_path.read_text() == "1"


# ── cc history ─────────────────────────────────────────────────────

class TestCcHistory:
    def test_history_with_no_data(
        self, runner: CliRunner, empty_log: Path
    ) -> None:
        with _patch_tracker_log(empty_log):
            result = runner.invoke(main, ["cc", "history"])
        assert result.exit_code == 0
        assert "no session history" in result.output.lower()

    def test_history_nonexistent_log(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        with _patch_tracker_log(tmp_path / "nope.jsonl"):
            result = runner.invoke(main, ["cc", "history"])
        assert result.exit_code == 0

    def test_history_with_data(
        self, runner: CliRunner, log_with_data: Path
    ) -> None:
        with _patch_tracker_log(log_with_data):
            result = runner.invoke(main, ["cc", "history"])
        assert result.exit_code == 0
        # Should show either a rich table or plain output with session info.
        # The output should not be empty.
        assert len(result.output.strip()) > 0

    def test_history_days_flag(
        self, runner: CliRunner, log_with_data: Path
    ) -> None:
        with _patch_tracker_log(log_with_data):
            result = runner.invoke(main, ["cc", "history", "--days", "1"])
        assert result.exit_code == 0


# ── cc tips ────────────────────────────────────────────────────────

class TestCcTips:
    def test_tips_with_no_data(
        self, runner: CliRunner, empty_log: Path
    ) -> None:
        with _patch_tracker_log(empty_log):
            result = runner.invoke(main, ["cc", "tips"])
        assert result.exit_code == 0
        assert "no session data" in result.output.lower()

    def test_tips_nonexistent_log(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        with _patch_tracker_log(tmp_path / "nope.jsonl"):
            result = runner.invoke(main, ["cc", "tips"])
        assert result.exit_code == 0

    def test_tips_with_data_no_crash(
        self, runner: CliRunner, log_with_data: Path
    ) -> None:
        with _patch_tracker_log(log_with_data):
            result = runner.invoke(main, ["cc", "tips"])
        assert result.exit_code == 0

    def test_tips_with_wasted_events(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        """Session with wasted events should produce tips."""
        log = tmp_path / "sessions.jsonl"
        events = [
            _make_event(tool="Bash", ts="2026-03-30T10:00:00", has_error=True),
            _make_event(tool="Bash", ts="2026-03-30T10:00:10", output_text="Error: fail"),
            _make_event(tool="Edit", ts="2026-03-30T10:00:20"),
        ]
        _write_log(log, events)

        with _patch_tracker_log(log):
            result = runner.invoke(main, ["cc", "tips"])
        assert result.exit_code == 0


# ── cc group help ──────────────────────────────────────────────────

class TestCcGroup:
    def test_cc_help(self, runner: CliRunner) -> None:
        result = runner.invoke(main, ["cc", "--help"])
        assert result.exit_code == 0
        assert "status" in result.output
        assert "score" in result.output

    def test_main_help(self, runner: CliRunner) -> None:
        result = runner.invoke(main, ["--help"])
        assert result.exit_code == 0
        assert "cc" in result.output


# ── cc export ──────────────────────────────────────────────────────

def _patch_claude_storage(db_path: Path, jsonl_path: Path):
    """Patch ClaudeStorage so the CLI uses a temp db and temp JSONL."""
    from unittest.mock import patch, MagicMock

    original_init = __import__("spent.storage", fromlist=["ClaudeStorage"]).ClaudeStorage.__init__

    def _patched_init(self, db_path_arg=None):
        original_init(self, db_path=db_path)
        # Override the JSONL default so import_from_jsonl reads our file.
        import spent.storage as _storage_mod
        _storage_mod.DEFAULT_JSONL_PATH = jsonl_path

    return patch("spent.storage.ClaudeStorage.__init__", _patched_init)


class TestCcExport:
    def test_export_help(self, runner: CliRunner) -> None:
        """The export subcommand must respond to --help with exit code 0."""
        result = runner.invoke(main, ["cc", "export", "--help"])
        assert result.exit_code == 0
        assert "export" in result.output.lower() or "format" in result.output.lower()

    def test_export_sqlite_no_data(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        """Running export when the JSONL file is absent must not crash."""
        empty_jsonl = tmp_path / "nonexistent.jsonl"  # does not exist
        db_path = tmp_path / "export_test.db"

        from unittest.mock import patch
        import spent.storage as _storage_mod

        original_default = _storage_mod.DEFAULT_JSONL_PATH
        try:
            _storage_mod.DEFAULT_JSONL_PATH = empty_jsonl
            with patch("spent.storage.DEFAULT_DB_PATH", db_path):
                result = runner.invoke(main, ["cc", "export"])
        finally:
            _storage_mod.DEFAULT_JSONL_PATH = original_default

        assert result.exit_code == 0

    def test_export_json_format(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        """Export with --format json should include JSON with sessions and model_breakdown."""
        jsonl_path = tmp_path / "sessions.jsonl"
        db_path = tmp_path / "export_json.db"
        _write_log(jsonl_path, _session_events(count=3))

        import spent.storage as _storage_mod

        original_default_jsonl = _storage_mod.DEFAULT_JSONL_PATH
        original_default_db = _storage_mod.DEFAULT_DB_PATH
        try:
            _storage_mod.DEFAULT_JSONL_PATH = jsonl_path
            _storage_mod.DEFAULT_DB_PATH = db_path
            result = runner.invoke(main, ["cc", "export", "--format", "json"])
        finally:
            _storage_mod.DEFAULT_JSONL_PATH = original_default_jsonl
            _storage_mod.DEFAULT_DB_PATH = original_default_db

        assert result.exit_code == 0

        # The CLI may emit a status line before the JSON object; find the JSON
        # block by locating the first '{'.
        output = result.output
        json_start = output.find("{")
        assert json_start != -1, f"No JSON object found in output: {output!r}"
        parsed = json.loads(output[json_start:])
        assert "sessions" in parsed
        assert "model_breakdown" in parsed
