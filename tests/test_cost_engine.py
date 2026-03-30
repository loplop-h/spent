"""Tests for the shared cost estimation and classification engine."""

import pytest

from spent.cost_engine import (
    estimate_cost,
    classify_event,
    compute_efficiency_score,
    generate_tips,
    EventData,
    MODEL_PRICING,
)


# ── Cost estimation tests ───────────────────────────────────────────

class TestEstimateCost:
    def test_basic_sonnet(self):
        inp_tok, out_tok, cost = estimate_cost(400, 200, turn_number=0, model="sonnet")
        assert inp_tok > 0
        assert out_tok > 0
        assert cost > 0

    def test_cost_increases_with_turn_number(self):
        _, _, cost0 = estimate_cost(100, 100, turn_number=0)
        _, _, cost10 = estimate_cost(100, 100, turn_number=10)
        assert cost10 > cost0  # context overhead grows

    def test_opus_more_expensive_than_sonnet(self):
        _, _, opus = estimate_cost(1000, 1000, turn_number=5, model="opus")
        _, _, sonnet = estimate_cost(1000, 1000, turn_number=5, model="sonnet")
        assert opus > sonnet

    def test_haiku_cheapest(self):
        _, _, haiku = estimate_cost(1000, 1000, turn_number=5, model="haiku")
        _, _, sonnet = estimate_cost(1000, 1000, turn_number=5, model="sonnet")
        assert haiku < sonnet

    def test_unknown_model_defaults_to_sonnet(self):
        _, _, unknown = estimate_cost(1000, 1000, turn_number=5, model="unknown")
        _, _, sonnet = estimate_cost(1000, 1000, turn_number=5, model="sonnet")
        assert unknown == sonnet

    def test_zero_input_uses_minimum(self):
        inp_tok, _, _ = estimate_cost(0, 0, turn_number=0)
        assert inp_tok >= 500  # MIN_INPUT_TOKENS

    def test_zero_output_uses_minimum(self):
        _, out_tok, _ = estimate_cost(0, 0, turn_number=0)
        assert out_tok >= 50  # MIN_OUTPUT_TOKENS

    def test_large_input(self):
        inp_tok, _, cost = estimate_cost(100000, 50000, turn_number=20)
        assert inp_tok > 25000
        assert cost > 0

    def test_all_models_have_pricing(self):
        for model in MODEL_PRICING:
            _, _, cost = estimate_cost(1000, 500, turn_number=0, model=model)
            assert cost > 0


# ── Classification tests ────────────────────────────────────────────

class TestClassifyEvent:
    def _make_events(self, *tools_data):
        """Helper: create EventData list from (tool, kwargs) tuples."""
        events = []
        base_ts = "2026-03-30T10:00:"
        for i, item in enumerate(tools_data):
            if isinstance(item, str):
                events.append(EventData(tool=item, ts=f"{base_ts}{i:02d}"))
            else:
                tool, kwargs = item[0], item[1]
                events.append(EventData(tool=tool, ts=f"{base_ts}{i:02d}", **kwargs))
        return events

    def test_edit_is_productive(self):
        events = self._make_events("Edit")
        assert classify_event(events[0], 0, events) == "productive"

    def test_write_is_productive(self):
        events = self._make_events("Write")
        assert classify_event(events[0], 0, events) == "productive"

    def test_agent_is_productive(self):
        events = self._make_events("Agent")
        assert classify_event(events[0], 0, events) == "productive"

    def test_read_is_neutral(self):
        events = self._make_events("Read")
        assert classify_event(events[0], 0, events) == "neutral"

    def test_grep_is_neutral(self):
        events = self._make_events("Grep")
        assert classify_event(events[0], 0, events) == "neutral"

    def test_glob_is_neutral(self):
        events = self._make_events("Glob")
        assert classify_event(events[0], 0, events) == "neutral"

    def test_bash_success_is_productive(self):
        events = self._make_events(("Bash", {"output_text": "Tests passed"}))
        assert classify_event(events[0], 0, events) == "productive"

    def test_bash_error_flag_is_wasted(self):
        events = self._make_events(("Bash", {"has_error": True}))
        assert classify_event(events[0], 0, events) == "wasted"

    def test_bash_error_keyword_is_wasted(self):
        events = self._make_events(("Bash", {"output_text": "Error: module not found"}))
        assert classify_event(events[0], 0, events) == "wasted"

    def test_bash_traceback_is_wasted(self):
        events = self._make_events(("Bash", {"output_text": "Traceback (most recent call last)"}))
        assert classify_event(events[0], 0, events) == "wasted"

    def test_bash_failed_is_wasted(self):
        events = self._make_events(("Bash", {"output_text": "Build failed with 3 errors"}))
        assert classify_event(events[0], 0, events) == "wasted"

    def test_repeated_read_same_file_is_wasted(self):
        events = [
            EventData(tool="Read", ts="2026-03-30T10:00:00", file_path="main.py"),
            EventData(tool="Read", ts="2026-03-30T10:00:30", file_path="main.py"),
        ]
        assert classify_event(events[0], 0, events) == "neutral"  # first is ok
        assert classify_event(events[1], 1, events) == "wasted"   # second within 60s

    def test_repeated_read_different_file_not_wasted(self):
        events = [
            EventData(tool="Read", ts="2026-03-30T10:00:00", file_path="main.py"),
            EventData(tool="Read", ts="2026-03-30T10:00:30", file_path="utils.py"),
        ]
        assert classify_event(events[1], 1, events) == "neutral"

    def test_repeated_read_after_60s_not_wasted(self):
        events = [
            EventData(tool="Read", ts="2026-03-30T10:00:00", file_path="main.py"),
            EventData(tool="Read", ts="2026-03-30T10:02:00", file_path="main.py"),
        ]
        assert classify_event(events[1], 1, events) == "neutral"

    def test_rapid_re_edit_is_wasted(self):
        events = [
            EventData(tool="Edit", ts="2026-03-30T10:00:00", file_path="main.py"),
            EventData(tool="Edit", ts="2026-03-30T10:00:15", file_path="main.py"),
        ]
        assert classify_event(events[0], 0, events) == "productive"  # first is ok
        assert classify_event(events[1], 1, events) == "wasted"      # second within 30s

    def test_rapid_edit_different_file_not_wasted(self):
        events = [
            EventData(tool="Edit", ts="2026-03-30T10:00:00", file_path="main.py"),
            EventData(tool="Edit", ts="2026-03-30T10:00:15", file_path="utils.py"),
        ]
        assert classify_event(events[1], 1, events) == "productive"

    def test_unknown_tool_is_neutral(self):
        events = self._make_events("SomeNewTool")
        assert classify_event(events[0], 0, events) == "neutral"


# ── Efficiency score tests ──────────────────────────────────────────

class TestEfficiencyScore:
    def test_all_productive(self):
        assert compute_efficiency_score(10.0, 0.0, 0.0) == 100.0

    def test_all_wasted(self):
        assert compute_efficiency_score(0.0, 0.0, 10.0) == 0.0

    def test_all_neutral(self):
        assert compute_efficiency_score(0.0, 10.0, 0.0) == 50.0

    def test_mixed(self):
        score = compute_efficiency_score(6.0, 3.0, 1.0)
        assert 70 < score < 80  # (6 + 1.5) / 10 = 75%

    def test_zero_cost(self):
        assert compute_efficiency_score(0.0, 0.0, 0.0) == 0.0


# ── Tips generation tests ──────────────────────────────────────────

class TestGenerateTips:
    def test_no_tips_when_clean(self):
        tips = generate_tips(
            by_tool={"Edit": {"cost": 0.05, "count": 5}},
            total_cost=0.05,
            wasted_cost=0.0,
            timeline=[{"tool": "Edit", "status": "productive"}],
        )
        # May or may not have tips about Edit being 100%, but no wasted tip
        assert not any("wasted" in t for t in tips)

    def test_wasted_tip(self):
        tips = generate_tips(
            by_tool={}, total_cost=0.10, wasted_cost=0.03,
            timeline=[{"status": "wasted"}, {"status": "wasted"}, {"status": "wasted"}],
        )
        assert any("wasted" in t.lower() for t in tips)

    def test_repeated_read_tip(self):
        timeline = [
            {"tool": "Read", "file_path": "main.py", "status": "neutral"},
            {"tool": "Read", "file_path": "main.py", "status": "neutral"},
            {"tool": "Read", "file_path": "main.py", "status": "wasted"},
        ]
        tips = generate_tips(
            by_tool={"Read": {"cost": 0.03, "count": 3}},
            total_cost=0.03, wasted_cost=0.01, timeline=timeline,
        )
        assert any("main.py" in t for t in tips)

    def test_expensive_tool_tip(self):
        tips = generate_tips(
            by_tool={"Agent": {"cost": 0.08, "count": 2}, "Read": {"cost": 0.02, "count": 5}},
            total_cost=0.10, wasted_cost=0.0, timeline=[],
        )
        assert any("Agent" in t for t in tips)
