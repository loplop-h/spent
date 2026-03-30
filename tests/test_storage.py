"""Tests for the storage module."""

import tempfile
from pathlib import Path

import pytest

from spent.storage import Storage


@pytest.fixture
def storage(tmp_path):
    """Create a storage instance with a temporary database."""
    db_path = tmp_path / "test.db"
    return Storage(db_path=db_path)


class TestStorage:
    def test_record_and_retrieve(self, storage):
        storage.record(
            session_id="test-001",
            provider="openai",
            model="gpt-4o",
            input_tokens=1000,
            output_tokens=500,
            cost=0.0075,
        )
        records = storage.get_session("test-001")
        assert len(records) == 1
        assert records[0]["model"] == "gpt-4o"
        assert records[0]["cost"] == 0.0075

    def test_multiple_records(self, storage):
        for i in range(5):
            storage.record(
                session_id="test-002",
                provider="openai",
                model="gpt-4o",
                input_tokens=1000 * (i + 1),
                output_tokens=500,
                cost=0.01 * (i + 1),
            )
        records = storage.get_session("test-002")
        assert len(records) == 5

    def test_sessions_summary(self, storage):
        storage.record("s1", "openai", "gpt-4o", 1000, 500, 0.01)
        storage.record("s1", "openai", "gpt-4o", 2000, 1000, 0.02)
        storage.record("s2", "anthropic", "claude-sonnet-4-6", 500, 200, 0.005)

        sessions = storage.get_sessions()
        assert len(sessions) == 2
        # Most recent session first
        s1 = next(s for s in sessions if s["session_id"] == "s1")
        assert s1["calls"] == 2
        assert abs(s1["total_cost"] - 0.03) < 1e-6

    def test_empty_session(self, storage):
        records = storage.get_session("nonexistent")
        assert records == []

    def test_total_cost(self, storage):
        storage.record("s1", "openai", "gpt-4o", 1000, 500, 1.50)
        storage.record("s2", "openai", "gpt-4o", 1000, 500, 2.50)
        assert abs(storage.get_total_cost() - 4.00) < 1e-6

    def test_total_cost_empty(self, storage):
        assert storage.get_total_cost() == 0.0

    def test_get_today(self, storage):
        storage.record("s1", "openai", "gpt-4o", 1000, 500, 0.01)
        records = storage.get_today()
        assert len(records) == 1

    def test_record_with_optional_fields(self, storage):
        storage.record(
            session_id="test-opt",
            provider="openai",
            model="gpt-4o",
            input_tokens=1000,
            output_tokens=500,
            cost=0.01,
            duration_ms=1234,
            tags=["experiment-1"],
            endpoint="chat.completions",
        )
        records = storage.get_session("test-opt")
        assert len(records) == 1
        assert records[0]["duration_ms"] == 1234
