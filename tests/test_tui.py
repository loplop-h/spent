"""Tests for the TUI module -- layout building and formatting helpers.

We do NOT test visual appearance. We verify that functions run without
crashing and return the expected types.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from spent.tui import (
    _build_layout,
    _fmt_duration,
    _make_bar,
)


# ── Helpers ────────────────────────────────────────────────────────

def _make_event(
    *,
    tool: str = "Edit",
    ts: str = "2026-03-30T10:00:00",
    session: str = "sess-001",
    event: str = "tool_use",
    input_size: int = 400,
    output_size: int = 200,
    output_text: str = "",
) -> dict[str, Any]:
    return {
        "ts": ts,
        "tool": tool,
        "session": session,
        "event": event,
        "input_size": input_size,
        "output_size": output_size,
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
        ts = (base + timedelta(minutes=i)).isoformat()
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


# ── _build_layout tests ───────────────────────────────────────────

class TestBuildLayout:
    """Verify _build_layout produces a renderable without crashing."""

    def _setup_log(self, tmp_path: Path, events: list[dict] | None = None):
        log = tmp_path / "sessions.jsonl"
        if events:
            _write_log(log, events)
        else:
            log.write_text("")
        return log

    def test_with_no_data(self, tmp_path: Path) -> None:
        log = tmp_path / "nope.jsonl"  # doesn't exist
        with patch("spent.claude_tracker.ClaudeTracker.LOG_PATH", log):
            result = _build_layout(80, 40)
        from rich.panel import Panel
        assert isinstance(result, Panel)

    def test_with_valid_session_data(self, tmp_path: Path) -> None:
        log = self._setup_log(tmp_path, _session_events(count=8))
        with patch("spent.claude_tracker.ClaudeTracker.LOG_PATH", log):
            result = _build_layout(80, 40)
        from rich.layout import Layout
        assert isinstance(result, Layout)

    def test_narrow_width_no_crash(self, tmp_path: Path) -> None:
        log = self._setup_log(tmp_path, _session_events())
        with patch("spent.claude_tracker.ClaudeTracker.LOG_PATH", log):
            result = _build_layout(40, 20)
        assert result is not None

    def test_wide_width_no_crash(self, tmp_path: Path) -> None:
        log = self._setup_log(tmp_path, _session_events())
        with patch("spent.claude_tracker.ClaudeTracker.LOG_PATH", log):
            result = _build_layout(200, 60)
        assert result is not None

    def test_single_event(self, tmp_path: Path) -> None:
        log = self._setup_log(tmp_path, [_make_event()])
        with patch("spent.claude_tracker.ClaudeTracker.LOG_PATH", log):
            result = _build_layout(80, 40)
        from rich.layout import Layout
        assert isinstance(result, Layout)


# ── _make_bar tests ────────────────────────────────────────────────

class TestMakeBar:
    def test_returns_string(self) -> None:
        result = _make_bar(50, 20)
        assert isinstance(result, str)

    def test_zero_percent(self) -> None:
        result = _make_bar(0, 20)
        assert isinstance(result, str)
        assert len(result) > 0

    def test_hundred_percent(self) -> None:
        result = _make_bar(100, 20)
        assert isinstance(result, str)

    def test_high_score_green(self) -> None:
        result = _make_bar(80, 20)
        assert "green" in result

    def test_medium_score_yellow(self) -> None:
        result = _make_bar(55, 20)
        assert "yellow" in result

    def test_low_score_red(self) -> None:
        result = _make_bar(20, 20)
        assert "red" in result

    def test_width_affects_bar(self) -> None:
        short = _make_bar(50, 5)
        long = _make_bar(50, 40)
        # The longer bar should contain more block characters.
        assert len(long) > len(short)


# ── _fmt_duration tests ───────────────────────────────────────────

class TestFmtDuration:
    def test_seconds_only(self) -> None:
        assert _fmt_duration(30) == "30s"

    def test_zero_seconds(self) -> None:
        assert _fmt_duration(0) == "0s"

    def test_one_second(self) -> None:
        assert _fmt_duration(1) == "1s"

    def test_exactly_60_seconds(self) -> None:
        result = _fmt_duration(60)
        assert result == "1m0s"

    def test_minutes_and_seconds(self) -> None:
        result = _fmt_duration(90)
        assert result == "1m30s"

    def test_many_minutes(self) -> None:
        result = _fmt_duration(5 * 60 + 45)
        assert result == "5m45s"

    def test_exactly_one_hour(self) -> None:
        result = _fmt_duration(3600)
        assert result == "1h0m"

    def test_hours_and_minutes(self) -> None:
        result = _fmt_duration(3600 + 1800)
        assert result == "1h30m"

    def test_multiple_hours(self) -> None:
        result = _fmt_duration(7200 + 900)
        assert result == "2h15m"

    def test_large_value(self) -> None:
        result = _fmt_duration(36000)
        assert "h" in result


# Tests for _compute, _read_events, _get_latest_session removed:
# consolidated into ClaudeTracker (tested in test_claude_tracker.py)

class _RemovedTestCompute:
    def test_empty_events(self) -> None:
        result = _compute([])
        assert result["score"] == 0
        assert result["total_cost"] == 0
        assert result["tool_uses"] == 0

    def test_no_tool_use_events(self) -> None:
        events = [
            {"event": "session_start", "ts": "2026-03-30T10:00:00", "tool": ""},
        ]
        result = _compute(events)
        assert result["tool_uses"] == 0
        assert result["score"] == 0

    def test_valid_events_produce_costs(self) -> None:
        events = _session_events(count=5)
        result = _compute(events)
        assert result["total_cost"] > 0
        assert result["tool_uses"] == 5
        assert len(result["timeline"]) == 5

    def test_by_tool_populated(self) -> None:
        events = _session_events(count=5)
        result = _compute(events)
        assert len(result["by_tool"]) > 0
        for name, info in result["by_tool"].items():
            assert "count" in info
            assert "cost" in info

    def test_tips_is_list(self) -> None:
        events = _session_events(count=5)
        result = _compute(events)
        assert isinstance(result["tips"], list)


# ── _read_events tests ─────────────────────────────────────────────

class _RemovedTestReadEvents:
    def test_missing_file(self, tmp_path: Path) -> None:
        with patch("spent.tui.LOG_PATH", tmp_path / "nope.jsonl"):
            result = _read_events()
        assert result == []

    def test_valid_file(self, tmp_path: Path) -> None:
        log = tmp_path / "sessions.jsonl"
        _write_log(log, _session_events(count=3))
        with patch("spent.tui.LOG_PATH", log):
            result = _read_events()
        assert len(result) == 3

    def test_corrupt_lines_skipped(self, tmp_path: Path) -> None:
        log = tmp_path / "sessions.jsonl"
        with open(log, "w", encoding="utf-8") as f:
            f.write(json.dumps(_make_event()) + "\n")
            f.write("not json\n")
            f.write(json.dumps(_make_event(tool="Write")) + "\n")
        with patch("spent.tui.LOG_PATH", log):
            result = _read_events()
        assert len(result) == 2


# ── _get_latest_session tests ──────────────────────────────────────

class _RemovedTestGetLatestSession:
    def test_empty_events(self) -> None:
        sid, evs = _get_latest_session([])
        assert sid == ""
        assert evs == []

    def test_single_session(self) -> None:
        events = _session_events(count=3)
        sid, evs = _get_latest_session(events)
        assert sid == "sess-001"
        assert len(evs) == 3

    def test_multiple_sessions_returns_last(self) -> None:
        events_a = _session_events(count=2, session_id="aaa")
        events_b = _session_events(count=3, session_id="bbb", start="2026-03-30T11:00:00")
        sid, evs = _get_latest_session(events_a + events_b)
        assert sid == "bbb"
        assert len(evs) == 3
