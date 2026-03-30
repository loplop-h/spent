"""Tests for ClaudeTracker -- JSONL-based session cost tracker."""

from __future__ import annotations

import json
import textwrap
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from spent.claude_tracker import ClaudeTracker, ToolEvent
from spent.cost_engine import ModelPricing, PRODUCTIVE_TOOLS, NEUTRAL_TOOLS, MODEL_PRICING


# ── Fixtures ───────────────────────────────────────────────────────

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
    """Build a JSONL-compatible event dict."""
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


def _write_jsonl(path: Path, events: list[dict[str, Any]]) -> None:
    """Write a list of dicts as JSONL."""
    with open(path, "w", encoding="utf-8") as f:
        for ev in events:
            f.write(json.dumps(ev) + "\n")


def _make_session_events(
    session_id: str = "sess-001",
    count: int = 5,
    start_ts: str = "2026-03-30T10:00:00",
) -> list[dict[str, Any]]:
    """Generate a sequence of tool_use events for a session."""
    base = datetime.fromisoformat(start_ts)
    events = []
    tools = ["Read", "Grep", "Edit", "Write", "Bash"]
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


@pytest.fixture()
def tracker_with_data(tmp_path: Path) -> tuple[ClaudeTracker, Path]:
    """Create a tracker backed by a temp JSONL file with one session."""
    log = tmp_path / "sessions.jsonl"
    events = _make_session_events()
    _write_jsonl(log, events)
    return (ClaudeTracker(log_path=log), log)


@pytest.fixture()
def empty_tracker(tmp_path: Path) -> ClaudeTracker:
    """Tracker pointing at a nonexistent file."""
    return ClaudeTracker(log_path=tmp_path / "nonexistent.jsonl")


# ── ToolEvent.from_line tests ──────────────────────────────────────

class TestToolEventFromLine:
    def test_valid_line(self) -> None:
        line = json.dumps(_make_event())
        ev = ToolEvent.from_line(line)
        assert ev is not None
        assert ev.tool == "Edit"
        assert ev.session == "sess-001"

    def test_empty_string_returns_none(self) -> None:
        assert ToolEvent.from_line("") is None

    def test_invalid_json_returns_none(self) -> None:
        assert ToolEvent.from_line("{bad json") is None

    def test_non_dict_json_returns_none(self) -> None:
        assert ToolEvent.from_line('"just a string"') is None

    def test_missing_fields_use_defaults(self) -> None:
        ev = ToolEvent.from_line("{}")
        assert ev is not None
        assert ev.tool == ""
        assert ev.session == ""
        assert ev.model == "sonnet"
        assert ev.event == "tool_use"
        assert ev.has_error is False

    def test_has_error_flag_parsed(self) -> None:
        line = json.dumps(_make_event(has_error=True))
        ev = ToolEvent.from_line(line)
        assert ev is not None
        assert ev.has_error is True

    def test_output_text_parsed(self) -> None:
        line = json.dumps(_make_event(output_text="hello world"))
        ev = ToolEvent.from_line(line)
        assert ev is not None
        assert ev.output_text == "hello world"


# ── get_current_session tests ──────────────────────────────────────

class TestGetCurrentSession:
    def test_returns_metrics_with_data(
        self, tracker_with_data: tuple[ClaudeTracker, Path]
    ) -> None:
        tracker, _ = tracker_with_data
        session = tracker.get_current_session()

        assert session["session_id"] == "sess-001"
        assert session["started"] != ""
        assert session["duration_minutes"] >= 0
        assert session["total_cost"] > 0
        assert session["tool_uses"] == 5
        assert isinstance(session["by_tool"], dict)
        assert isinstance(session["efficiency"], dict)
        assert isinstance(session["timeline"], list)

    def test_empty_file_returns_empty_session(
        self, empty_tracker: ClaudeTracker
    ) -> None:
        session = empty_tracker.get_current_session()

        assert session["session_id"] == ""
        assert session["total_cost"] == 0.0
        assert session["tool_uses"] == 0
        assert session["by_tool"] == {}
        assert session["timeline"] == []
        assert session["efficiency"]["productive"] == 0.0
        assert session["efficiency"]["wasted"] == 0.0
        assert session["efficiency"]["neutral"] == 0.0

    def test_corrupt_lines_skipped_gracefully(self, tmp_path: Path) -> None:
        """Corrupt lines mixed with valid ones should be skipped."""
        log = tmp_path / "sessions.jsonl"
        valid = _make_event(tool="Edit", ts="2026-03-30T10:00:00")
        with open(log, "w", encoding="utf-8") as f:
            f.write(json.dumps(valid) + "\n")
            f.write("THIS IS NOT JSON\n")
            f.write("{broken: json,}\n")
            f.write("\n")  # blank line
            f.write(json.dumps(
                _make_event(tool="Write", ts="2026-03-30T10:01:00")
            ) + "\n")

        tracker = ClaudeTracker(log_path=log)
        session = tracker.get_current_session()

        assert session["tool_uses"] == 2
        assert "Edit" in session["by_tool"]
        assert "Write" in session["by_tool"]

    def test_session_metrics_keys(
        self, tracker_with_data: tuple[ClaudeTracker, Path]
    ) -> None:
        """Verify all expected keys exist in session metrics."""
        tracker, _ = tracker_with_data
        session = tracker.get_current_session()

        required_keys = {
            "session_id", "started", "duration_minutes", "total_cost",
            "total_tokens", "tool_uses", "by_tool", "efficiency", "timeline",
        }
        assert required_keys.issubset(session.keys())

        efficiency_keys = {"productive", "wasted", "neutral"}
        assert efficiency_keys == set(session["efficiency"].keys())


# ── Multiple sessions tests ────────────────────────────────────────

class TestMultipleSessions:
    def test_get_current_session_returns_last_session(
        self, tmp_path: Path
    ) -> None:
        """With two sessions in the file, get_current_session returns the last."""
        log = tmp_path / "sessions.jsonl"
        events_a = _make_session_events("sess-AAA", count=3, start_ts="2026-03-30T09:00:00")
        events_b = _make_session_events("sess-BBB", count=4, start_ts="2026-03-30T11:00:00")
        _write_jsonl(log, events_a + events_b)

        tracker = ClaudeTracker(log_path=log)
        session = tracker.get_current_session()

        assert session["session_id"] == "sess-BBB"
        assert session["tool_uses"] == 4

    def test_group_sessions_separates_by_id(self, tmp_path: Path) -> None:
        log = tmp_path / "sessions.jsonl"
        events_a = _make_session_events("sess-AAA", count=2, start_ts="2026-03-30T09:00:00")
        events_b = _make_session_events("sess-BBB", count=3, start_ts="2026-03-30T09:30:00")
        _write_jsonl(log, events_a + events_b)

        tracker = ClaudeTracker(log_path=log)
        # Use get_session_history with a wide window to get all.
        sessions = tracker.get_session_history(days=30)

        assert len(sessions) == 2
        ids = {s["session_id"] for s in sessions}
        assert ids == {"sess-AAA", "sess-BBB"}

    def test_interleaved_session_events(self, tmp_path: Path) -> None:
        """Events from two sessions interleaved should still group correctly."""
        log = tmp_path / "sessions.jsonl"
        events = [
            _make_event(session="s1", tool="Edit", ts="2026-03-30T10:00:00"),
            _make_event(session="s2", tool="Read", ts="2026-03-30T10:00:01"),
            _make_event(session="s1", tool="Write", ts="2026-03-30T10:00:02"),
            _make_event(session="s2", tool="Grep", ts="2026-03-30T10:00:03"),
        ]
        _write_jsonl(log, events)

        tracker = ClaudeTracker(log_path=log)
        sessions = tracker.get_session_history(days=30)

        assert len(sessions) == 2
        s1 = next(s for s in sessions if s["session_id"] == "s1")
        s2 = next(s for s in sessions if s["session_id"] == "s2")
        assert s1["tool_uses"] == 2
        assert s2["tool_uses"] == 2


# ── get_today_sessions tests ───────────────────────────────────────

class TestGetTodaySessions:
    def test_returns_today_only(self, tmp_path: Path) -> None:
        log = tmp_path / "sessions.jsonl"
        today = datetime.now(timezone.utc).strftime("%Y-%m-%dT12:00:00")
        yesterday = (
            datetime.now(timezone.utc) - timedelta(days=1)
        ).strftime("%Y-%m-%dT12:00:00")

        events = [
            _make_event(session="old", ts=yesterday, tool="Edit"),
            _make_event(session="today", ts=today, tool="Write"),
        ]
        _write_jsonl(log, events)

        tracker = ClaudeTracker(log_path=log)
        sessions = tracker.get_today_sessions()

        assert len(sessions) == 1
        assert sessions[0]["session_id"] == "today"

    def test_empty_when_no_today_data(self, empty_tracker: ClaudeTracker) -> None:
        assert empty_tracker.get_today_sessions() == []


# ── get_session_history tests ──────────────────────────────────────

class TestGetSessionHistory:
    def test_filters_by_date(self, tmp_path: Path) -> None:
        log = tmp_path / "sessions.jsonl"
        now = datetime.now(timezone.utc)
        recent_ts = (now - timedelta(days=2)).isoformat()
        old_ts = (now - timedelta(days=15)).isoformat()

        events = [
            _make_event(session="old", ts=old_ts, tool="Edit"),
            _make_event(session="recent", ts=recent_ts, tool="Write"),
        ]
        _write_jsonl(log, events)

        tracker = ClaudeTracker(log_path=log)

        week = tracker.get_session_history(days=7)
        assert len(week) == 1
        assert week[0]["session_id"] == "recent"

        month = tracker.get_session_history(days=30)
        assert len(month) == 2

    def test_empty_result(self, empty_tracker: ClaudeTracker) -> None:
        assert empty_tracker.get_session_history(days=7) == []


# ── get_efficiency_score tests ─────────────────────────────────────

class TestGetEfficiencyScore:
    def _make_tracker(self) -> ClaudeTracker:
        return ClaudeTracker(log_path=Path("/nonexistent"))

    def test_all_productive(self) -> None:
        tracker = self._make_tracker()
        session = {"efficiency": {"productive": 10.0, "wasted": 0.0, "neutral": 0.0}}
        assert tracker.get_efficiency_score(session) == 100.0

    def test_all_wasted(self) -> None:
        tracker = self._make_tracker()
        session = {"efficiency": {"productive": 0.0, "wasted": 10.0, "neutral": 0.0}}
        assert tracker.get_efficiency_score(session) == 0.0

    def test_all_neutral(self) -> None:
        tracker = self._make_tracker()
        session = {"efficiency": {"productive": 0.0, "wasted": 0.0, "neutral": 10.0}}
        assert tracker.get_efficiency_score(session) == 50.0

    def test_mixed_score(self) -> None:
        tracker = self._make_tracker()
        session = {"efficiency": {"productive": 6.0, "wasted": 1.0, "neutral": 3.0}}
        # (6*1.0 + 3*0.5 + 1*0.0) / 10 = 7.5/10 = 75%
        assert tracker.get_efficiency_score(session) == 75.0

    def test_zero_cost_returns_zero(self) -> None:
        tracker = self._make_tracker()
        session = {"efficiency": {"productive": 0.0, "wasted": 0.0, "neutral": 0.0}}
        assert tracker.get_efficiency_score(session) == 0.0

    def test_missing_efficiency_key(self) -> None:
        tracker = self._make_tracker()
        session: dict[str, Any] = {}
        assert tracker.get_efficiency_score(session) == 0.0

    def test_matches_cost_engine_formula(self) -> None:
        """Verify parity with cost_engine.compute_efficiency_score."""
        from spent.cost_engine import compute_efficiency_score

        tracker = self._make_tracker()
        cases = [
            (10.0, 0.0, 0.0),
            (0.0, 10.0, 0.0),
            (0.0, 0.0, 10.0),
            (5.0, 3.0, 2.0),
            (1.5, 0.5, 0.0),
        ]
        for productive, neutral, wasted in cases:
            session = {
                "efficiency": {
                    "productive": productive,
                    "neutral": neutral,
                    "wasted": wasted,
                }
            }
            tracker_score = tracker.get_efficiency_score(session)
            engine_score = compute_efficiency_score(productive, neutral, wasted)
            assert tracker_score == engine_score, (
                f"Mismatch for p={productive}, n={neutral}, w={wasted}: "
                f"tracker={tracker_score}, engine={engine_score}"
            )


# ── Classification / wasted detection tests ────────────────────────

class TestClassification:
    def test_has_error_flag_classified_as_wasted(self, tmp_path: Path) -> None:
        log = tmp_path / "sessions.jsonl"
        events = [
            _make_event(
                tool="Bash",
                ts="2026-03-30T10:00:00",
                has_error=True,
                output_text="",
            ),
        ]
        _write_jsonl(log, events)

        tracker = ClaudeTracker(log_path=log)
        session = tracker.get_current_session()

        # The single event should be classified as wasted.
        assert session["efficiency"]["wasted"] > 0
        assert session["timeline"][0]["status"] == "wasted"

    def test_bash_error_keyword_in_output_classified_as_wasted(
        self, tmp_path: Path
    ) -> None:
        log = tmp_path / "sessions.jsonl"
        events = [
            _make_event(
                tool="Bash",
                ts="2026-03-30T10:00:00",
                output_text="Traceback (most recent call last): ...",
            ),
        ]
        _write_jsonl(log, events)

        tracker = ClaudeTracker(log_path=log)
        session = tracker.get_current_session()

        assert session["efficiency"]["wasted"] > 0
        assert session["timeline"][0]["status"] == "wasted"

    def test_bash_permission_denied_classified_as_wasted(
        self, tmp_path: Path
    ) -> None:
        log = tmp_path / "sessions.jsonl"
        events = [
            _make_event(
                tool="Bash",
                ts="2026-03-30T10:00:00",
                output_text="permission denied: /etc/shadow",
            ),
        ]
        _write_jsonl(log, events)

        tracker = ClaudeTracker(log_path=log)
        session = tracker.get_current_session()
        assert session["timeline"][0]["status"] == "wasted"

    def test_bash_success_classified_as_productive(
        self, tmp_path: Path
    ) -> None:
        log = tmp_path / "sessions.jsonl"
        events = [
            _make_event(
                tool="Bash",
                ts="2026-03-30T10:00:00",
                output_text="All tests passed.",
            ),
        ]
        _write_jsonl(log, events)

        tracker = ClaudeTracker(log_path=log)
        session = tracker.get_current_session()

        assert session["efficiency"]["productive"] > 0
        assert session["timeline"][0]["status"] == "productive"

    def test_edit_is_productive(self, tmp_path: Path) -> None:
        log = tmp_path / "sessions.jsonl"
        events = [
            _make_event(tool="Edit", ts="2026-03-30T10:00:00"),
        ]
        _write_jsonl(log, events)

        tracker = ClaudeTracker(log_path=log)
        session = tracker.get_current_session()
        assert session["timeline"][0]["status"] == "productive"

    def test_read_is_neutral(self, tmp_path: Path) -> None:
        log = tmp_path / "sessions.jsonl"
        events = [
            _make_event(tool="Read", ts="2026-03-30T10:00:00"),
        ]
        _write_jsonl(log, events)

        tracker = ClaudeTracker(log_path=log)
        session = tracker.get_current_session()
        assert session["timeline"][0]["status"] == "neutral"

    def test_repeated_read_classified_as_wasted(self, tmp_path: Path) -> None:
        log = tmp_path / "sessions.jsonl"
        events = [
            _make_event(
                tool="Read", ts="2026-03-30T10:00:00",
                file_path="main.py", input_size=500,
            ),
            _make_event(
                tool="Read", ts="2026-03-30T10:00:30",
                file_path="main.py", input_size=500,
            ),
        ]
        _write_jsonl(log, events)

        tracker = ClaudeTracker(log_path=log)
        session = tracker.get_current_session()

        assert session["timeline"][0]["status"] == "neutral"
        assert session["timeline"][1]["status"] == "wasted"

    def test_rapid_re_edit_classified_as_wasted(self, tmp_path: Path) -> None:
        log = tmp_path / "sessions.jsonl"
        events = [
            _make_event(
                tool="Edit", ts="2026-03-30T10:00:00",
                file_path="main.py",
            ),
            _make_event(
                tool="Edit", ts="2026-03-30T10:00:15",
                file_path="main.py",
            ),
        ]
        _write_jsonl(log, events)

        tracker = ClaudeTracker(log_path=log)
        session = tracker.get_current_session()

        assert session["timeline"][0]["status"] == "productive"
        assert session["timeline"][1]["status"] == "wasted"


# ── Duration calculation tests ─────────────────────────────────────

class TestDuration:
    def test_duration_computed(
        self, tracker_with_data: tuple[ClaudeTracker, Path]
    ) -> None:
        tracker, _ = tracker_with_data
        session = tracker.get_current_session()
        # 5 events, each 2 minutes apart => 8 minutes total.
        assert session["duration_minutes"] == pytest.approx(8.0, abs=0.1)

    def test_single_event_zero_duration(self, tmp_path: Path) -> None:
        log = tmp_path / "sessions.jsonl"
        events = [_make_event(tool="Edit")]
        _write_jsonl(log, events)

        tracker = ClaudeTracker(log_path=log)
        session = tracker.get_current_session()
        assert session["duration_minutes"] == 0.0


# ── Cost estimation tests ──────────────────────────────────────────

class TestCostEstimation:
    def test_cost_positive_for_events(
        self, tracker_with_data: tuple[ClaudeTracker, Path]
    ) -> None:
        tracker, _ = tracker_with_data
        session = tracker.get_current_session()
        assert session["total_cost"] > 0

    def test_cost_grows_with_turn_number(self, tmp_path: Path) -> None:
        """Later events should cost more due to context overhead."""
        log = tmp_path / "sessions.jsonl"
        events = [
            _make_event(
                tool="Edit",
                ts=f"2026-03-30T10:00:{i:02d}",
                input_size=400,
                output_size=200,
            )
            for i in range(10)
        ]
        _write_jsonl(log, events)

        tracker = ClaudeTracker(log_path=log)
        session = tracker.get_current_session()
        timeline = session["timeline"]

        # Cost of the last event should exceed cost of the first.
        assert timeline[-1]["cost"] > timeline[0]["cost"]

    def test_by_tool_sums_match_total(self, tmp_path: Path) -> None:
        log = tmp_path / "sessions.jsonl"
        events = _make_session_events(count=8)
        _write_jsonl(log, events)

        tracker = ClaudeTracker(log_path=log)
        session = tracker.get_current_session()

        by_tool_total = sum(v["cost"] for v in session["by_tool"].values())
        assert by_tool_total == pytest.approx(session["total_cost"], rel=1e-4)

    def test_efficiency_costs_sum_to_total(self, tmp_path: Path) -> None:
        log = tmp_path / "sessions.jsonl"
        events = _make_session_events(count=6)
        _write_jsonl(log, events)

        tracker = ClaudeTracker(log_path=log)
        session = tracker.get_current_session()

        eff = session["efficiency"]
        eff_total = eff["productive"] + eff["wasted"] + eff["neutral"]
        assert eff_total == pytest.approx(session["total_cost"], rel=1e-4)


# ── Edge cases ─────────────────────────────────────────────────────

class TestEdgeCases:
    def test_file_does_not_exist(self, tmp_path: Path) -> None:
        tracker = ClaudeTracker(log_path=tmp_path / "nope.jsonl")
        assert tracker.get_current_session()["session_id"] == ""
        assert tracker.get_today_sessions() == []
        assert tracker.get_session_history(days=7) == []

    def test_empty_file(self, tmp_path: Path) -> None:
        log = tmp_path / "sessions.jsonl"
        log.write_text("")
        tracker = ClaudeTracker(log_path=log)
        session = tracker.get_current_session()
        assert session["session_id"] == ""

    def test_only_non_tool_use_events(self, tmp_path: Path) -> None:
        log = tmp_path / "sessions.jsonl"
        events = [
            _make_event(event="session_start", tool=""),
            _make_event(event="session_end", tool=""),
        ]
        _write_jsonl(log, events)

        tracker = ClaudeTracker(log_path=log)
        session = tracker.get_current_session()
        # session_start/end are not tool_use, so tool_uses should be 0.
        assert session["tool_uses"] == 0

    def test_session_with_all_corrupt_lines(self, tmp_path: Path) -> None:
        log = tmp_path / "sessions.jsonl"
        log.write_text("bad line 1\nbad line 2\n{broken}\n")

        tracker = ClaudeTracker(log_path=log)
        session = tracker.get_current_session()
        assert session["session_id"] == ""
        assert session["tool_uses"] == 0
