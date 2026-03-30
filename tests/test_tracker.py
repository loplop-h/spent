"""Tests for the tracker module."""

import pytest

from spent.tracker import Tracker


@pytest.fixture(autouse=True)
def reset_tracker():
    """Reset the global tracker before each test."""
    Tracker.reset()
    yield
    Tracker.reset()


@pytest.fixture
def tracker(tmp_path):
    """Create a tracker with a temporary database."""
    from spent.storage import Storage
    t = Tracker.get()
    t.storage = Storage(db_path=tmp_path / "test.db")
    return t


class TestTracker:
    def test_singleton(self):
        t1 = Tracker.get()
        t2 = Tracker.get()
        assert t1 is t2

    def test_reset(self):
        t1 = Tracker.get()
        Tracker.reset()
        t2 = Tracker.get()
        assert t1 is not t2

    def test_record_returns_cost(self, tracker):
        cost = tracker.record(
            provider="openai",
            model="gpt-4o",
            input_tokens=1000,
            output_tokens=500,
        )
        assert cost > 0

    def test_record_unknown_model(self, tracker):
        cost = tracker.record(
            provider="custom",
            model="my-custom-model",
            input_tokens=1000,
            output_tokens=500,
        )
        assert cost == 0.0

    def test_summary_structure(self, tracker):
        tracker.record("openai", "gpt-4o", 1000, 500)
        tracker.record("openai", "gpt-4o-mini", 2000, 1000)

        s = tracker.summary()
        assert "session_id" in s
        assert "total_cost" in s
        assert "total_input_tokens" in s
        assert "total_output_tokens" in s
        assert "total_tokens" in s
        assert "total_calls" in s
        assert "by_model" in s
        assert "savings" in s

    def test_summary_totals(self, tracker):
        tracker.record("openai", "gpt-4o", 1000, 500)
        tracker.record("openai", "gpt-4o", 2000, 1000)

        s = tracker.summary()
        assert s["total_calls"] == 2
        assert s["total_input_tokens"] == 3000
        assert s["total_output_tokens"] == 1500
        assert s["total_tokens"] == 4500

    def test_summary_by_model(self, tracker):
        tracker.record("openai", "gpt-4o", 1000, 500)
        tracker.record("openai", "gpt-4o-mini", 2000, 1000)

        s = tracker.summary()
        assert "gpt-4o" in s["by_model"]
        assert "gpt-4o-mini" in s["by_model"]
        assert s["by_model"]["gpt-4o"]["calls"] == 1
        assert s["by_model"]["gpt-4o-mini"]["calls"] == 1

    def test_savings_recommendations(self, tracker):
        # Record expensive model usage
        for _ in range(10):
            tracker.record("openai", "gpt-4", 10000, 5000)

        s = tracker.summary()
        assert len(s["savings"]) > 0
        assert s["savings"][0]["from"] == "gpt-4"

    def test_budget_not_set(self, tracker):
        tracker.record("openai", "gpt-4o", 1000, 500)
        s = tracker.summary()
        assert s["budget"] is None

    def test_budget_set(self, tracker):
        tracker.set_budget(10.00)
        s = tracker.summary()
        assert s["budget"] == 10.00

    def test_session_id_format(self, tracker):
        s = tracker.summary()
        assert len(s["session_id"]) == 8
