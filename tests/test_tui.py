"""Tests for the TUI module -- layout building and formatting helpers.

We do NOT test visual appearance. We verify that functions run without
crashing and return the expected types.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from spent.tui import (
    _build_layout,
    _fmt_duration,
    _make_bar,
)


# -- Helpers --------------------------------------------------------

def _make_session_data(
    *,
    session_id: str = "sess-001",
    total_cost: float = 0.0123,
    tool_uses: int = 5,
    duration_minutes: float = 8.0,
    productive: float = 0.008,
    neutral: float = 0.003,
    wasted: float = 0.0013,
    by_tool: dict[str, dict] | None = None,
    timeline: list[dict] | None = None,
) -> dict[str, Any]:
    """Build a session metrics dict matching ClaudeTracker output."""
    if by_tool is None:
        by_tool = {
            "Edit": {"count": 2, "cost": 0.005},
            "Read": {"count": 2, "cost": 0.004},
            "Bash": {"count": 1, "cost": 0.0033},
        }
    if timeline is None:
        timeline = [
            {"ts": "2026-03-30T10:00:00", "tool": "Read", "cost": 0.002, "status": "neutral"},
            {"ts": "2026-03-30T10:01:00", "tool": "Edit", "cost": 0.003, "status": "productive"},
            {"ts": "2026-03-30T10:02:00", "tool": "Bash", "cost": 0.003, "status": "productive"},
            {"ts": "2026-03-30T10:03:00", "tool": "Read", "cost": 0.002, "status": "neutral"},
            {"ts": "2026-03-30T10:04:00", "tool": "Edit", "cost": 0.002, "status": "productive"},
        ]
    return {
        "session_id": session_id,
        "started": "2026-03-30T10:00:00",
        "duration_minutes": duration_minutes,
        "total_cost": total_cost,
        "total_tokens": 12000,
        "tool_uses": tool_uses,
        "by_tool": by_tool,
        "efficiency": {
            "productive": productive,
            "wasted": wasted,
            "neutral": neutral,
        },
        "timeline": timeline,
    }


def _empty_session() -> dict[str, Any]:
    return {
        "session_id": "",
        "started": "",
        "duration_minutes": 0.0,
        "total_cost": 0.0,
        "total_tokens": 0,
        "tool_uses": 0,
        "by_tool": {},
        "efficiency": {"productive": 0.0, "wasted": 0.0, "neutral": 0.0},
        "timeline": [],
    }


def _patch_tracker(session_data: dict[str, Any], score: float = 65.0):
    """Return a context manager that mocks ClaudeTracker inside _build_layout."""
    mock_tracker = MagicMock()
    mock_tracker.get_current_session.return_value = session_data
    mock_tracker.get_efficiency_score.return_value = score
    mock_cls = MagicMock(return_value=mock_tracker)
    return patch("spent.claude_tracker.ClaudeTracker", mock_cls)


# -- _build_layout tests -------------------------------------------

class TestBuildLayout:
    """Verify _build_layout produces a renderable without crashing."""

    def test_with_no_session_id(self) -> None:
        with _patch_tracker(_empty_session()):
            result = _build_layout(80, 40)
        from rich.panel import Panel
        assert isinstance(result, Panel)

    def test_with_valid_session_data(self) -> None:
        with _patch_tracker(_make_session_data()):
            result = _build_layout(80, 40)
        from rich.layout import Layout
        assert isinstance(result, Layout)

    def test_narrow_width_no_crash(self) -> None:
        with _patch_tracker(_make_session_data()):
            result = _build_layout(40, 20)
        assert result is not None

    def test_wide_width_no_crash(self) -> None:
        with _patch_tracker(_make_session_data()):
            result = _build_layout(200, 60)
        assert result is not None

    def test_very_small_height(self) -> None:
        with _patch_tracker(_make_session_data()):
            result = _build_layout(80, 10)
        assert result is not None

    def test_single_tool_in_session(self) -> None:
        data = _make_session_data(
            tool_uses=1,
            total_cost=0.003,
            productive=0.003,
            neutral=0.0,
            wasted=0.0,
            by_tool={"Edit": {"count": 1, "cost": 0.003}},
            timeline=[
                {"ts": "2026-03-30T10:00:00", "tool": "Edit",
                 "cost": 0.003, "status": "productive"},
            ],
        )
        with _patch_tracker(data, score=100.0):
            result = _build_layout(80, 40)
        from rich.layout import Layout
        assert isinstance(result, Layout)

    def test_many_tools(self) -> None:
        by_tool = {
            name: {"count": 1, "cost": 0.001 * (i + 1)}
            for i, name in enumerate(
                ["Edit", "Write", "Read", "Grep", "Glob", "Bash", "Agent", "MultiEdit"]
            )
        }
        data = _make_session_data(tool_uses=8, total_cost=0.036, by_tool=by_tool)
        with _patch_tracker(data):
            result = _build_layout(80, 40)
        assert result is not None

    def test_zero_total_cost(self) -> None:
        data = _make_session_data(
            session_id="s1",
            total_cost=0.0,
            productive=0.0,
            neutral=0.0,
            wasted=0.0,
            by_tool={},
            timeline=[],
        )
        with _patch_tracker(data, score=0.0):
            result = _build_layout(80, 40)
        assert result is not None

    def test_high_efficiency_score(self) -> None:
        with _patch_tracker(_make_session_data(), score=95.0):
            result = _build_layout(80, 40)
        from rich.layout import Layout
        assert isinstance(result, Layout)

    def test_low_efficiency_score(self) -> None:
        with _patch_tracker(_make_session_data(), score=15.0):
            result = _build_layout(80, 40)
        from rich.layout import Layout
        assert isinstance(result, Layout)

    def test_tracker_exception_returns_error_panel(self) -> None:
        mock_cls = MagicMock(side_effect=RuntimeError("oops"))
        with patch("spent.claude_tracker.ClaudeTracker", mock_cls):
            result = _build_layout(80, 40)
        from rich.panel import Panel
        assert isinstance(result, Panel)

    def test_empty_timeline(self) -> None:
        data = _make_session_data(
            timeline=[],
            total_cost=0.005,
            by_tool={"Edit": {"count": 1, "cost": 0.005}},
        )
        with _patch_tracker(data):
            result = _build_layout(80, 40)
        assert result is not None


# -- _make_bar tests ------------------------------------------------

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
        assert len(long) > len(short)


# -- _fmt_duration tests --------------------------------------------

class TestFmtDuration:
    def test_seconds_only(self) -> None:
        assert _fmt_duration(30) == "30s"

    def test_zero_seconds(self) -> None:
        assert _fmt_duration(0) == "0s"

    def test_one_second(self) -> None:
        assert _fmt_duration(1) == "1s"

    def test_exactly_60_seconds(self) -> None:
        assert _fmt_duration(60) == "1m0s"

    def test_minutes_and_seconds(self) -> None:
        assert _fmt_duration(90) == "1m30s"

    def test_many_minutes(self) -> None:
        assert _fmt_duration(5 * 60 + 45) == "5m45s"

    def test_exactly_one_hour(self) -> None:
        assert _fmt_duration(3600) == "1h0m"

    def test_hours_and_minutes(self) -> None:
        assert _fmt_duration(3600 + 1800) == "1h30m"

    def test_multiple_hours(self) -> None:
        assert _fmt_duration(7200 + 900) == "2h15m"

    def test_large_value(self) -> None:
        result = _fmt_duration(36000)
        assert "h" in result
