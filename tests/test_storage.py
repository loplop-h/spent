"""Tests for the storage module."""

import csv
import json
import sqlite3
import tempfile
from pathlib import Path

import pytest

from spent.storage import Storage, ClaudeStorage


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


# ── ClaudeStorage tests ─────────────────────────────────────────────

def _make_jsonl_event(
    *,
    ts: str = "2026-04-01T10:00:00",
    event: str = "tool_use",
    session: str = "sess1234",
    tool: str = "Edit",
    model: str = "sonnet",
    input_size: int = 100,
    output_size: int = 50,
    has_error: bool = False,
    file_path: str = "test.py",
    output_text: str = "",
) -> dict:
    return {
        "ts": ts,
        "event": event,
        "session": session,
        "tool": tool,
        "model": model,
        "input_size": input_size,
        "output_size": output_size,
        "has_error": has_error,
        "file_path": file_path,
        "output_text": output_text,
    }


def _write_jsonl_file(path: Path, events: list[dict]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        for ev in events:
            f.write(json.dumps(ev) + "\n")


@pytest.fixture
def claude_storage(tmp_path: Path) -> ClaudeStorage:
    """ClaudeStorage backed by a temp SQLite database."""
    return ClaudeStorage(db_path=tmp_path / "claude_test.db")


class TestClaudeStorage:
    def test_init_creates_table(self, tmp_path: Path) -> None:
        """Initialising ClaudeStorage must create the claude_events table."""
        db_path = tmp_path / "new.db"
        ClaudeStorage(db_path=db_path)

        conn = sqlite3.connect(str(db_path))
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='claude_events'"
        ).fetchone()
        conn.close()

        assert row is not None, "claude_events table was not created"

    def test_import_from_jsonl(self, tmp_path: Path) -> None:
        """Importing a JSONL file with 3 events should return count 3."""
        jsonl = tmp_path / "events.jsonl"
        events = [
            _make_jsonl_event(ts="2026-04-01T10:00:00", session="s1", tool="Edit"),
            _make_jsonl_event(ts="2026-04-01T10:01:00", session="s1", tool="Read"),
            _make_jsonl_event(ts="2026-04-01T10:02:00", session="s1", tool="Bash"),
        ]
        _write_jsonl_file(jsonl, events)

        store = ClaudeStorage(db_path=tmp_path / "test.db")
        imported = store.import_from_jsonl(jsonl_path=jsonl)

        assert imported == 3

    def test_import_idempotent(self, tmp_path: Path) -> None:
        """Importing the same JSONL twice must not duplicate rows."""
        jsonl = tmp_path / "events.jsonl"
        events = [
            _make_jsonl_event(ts="2026-04-01T10:00:00", session="s1", tool="Edit"),
            _make_jsonl_event(ts="2026-04-01T10:01:00", session="s1", tool="Read"),
            _make_jsonl_event(ts="2026-04-01T10:02:00", session="s1", tool="Bash"),
        ]
        _write_jsonl_file(jsonl, events)

        store = ClaudeStorage(db_path=tmp_path / "test.db")
        store.import_from_jsonl(jsonl_path=jsonl)
        second_import = store.import_from_jsonl(jsonl_path=jsonl)

        assert second_import == 0  # nothing new imported

        conn = sqlite3.connect(str(store.db_path))
        total = conn.execute("SELECT COUNT(*) FROM claude_events").fetchone()[0]
        conn.close()
        assert total == 3

    def test_get_sessions(self, tmp_path: Path) -> None:
        """get_sessions should return one summary per distinct session_id."""
        jsonl = tmp_path / "events.jsonl"
        events = [
            _make_jsonl_event(ts="2026-04-01T10:00:00", session="sess-A", tool="Edit"),
            _make_jsonl_event(ts="2026-04-01T10:01:00", session="sess-A", tool="Read"),
            _make_jsonl_event(ts="2026-04-01T11:00:00", session="sess-B", tool="Write"),
        ]
        _write_jsonl_file(jsonl, events)

        store = ClaudeStorage(db_path=tmp_path / "test.db")
        store.import_from_jsonl(jsonl_path=jsonl)
        sessions = store.get_sessions()

        assert len(sessions) == 2
        ids = {s["session_id"] for s in sessions}
        assert ids == {"sess-A", "sess-B"}

    def test_get_sessions_with_project_filter(self, tmp_path: Path) -> None:
        """get_sessions(project=...) must filter by project tag."""
        jsonl = tmp_path / "events.jsonl"
        events = [
            _make_jsonl_event(ts="2026-04-01T10:00:00", session="sess-1", tool="Edit"),
            _make_jsonl_event(ts="2026-04-01T10:01:00", session="sess-2", tool="Read"),
        ]
        _write_jsonl_file(jsonl, events)

        store = ClaudeStorage(db_path=tmp_path / "test.db")
        store.import_from_jsonl(jsonl_path=jsonl, project="myapp")

        myapp_sessions = store.get_sessions(project="myapp")
        assert len(myapp_sessions) == 2

        other_sessions = store.get_sessions(project="other")
        assert len(other_sessions) == 0

    def test_get_model_breakdown(self, tmp_path: Path) -> None:
        """get_model_breakdown should aggregate events by model."""
        jsonl = tmp_path / "events.jsonl"
        events = [
            _make_jsonl_event(ts="2026-04-01T10:00:00", session="s1", tool="Edit", model="sonnet"),
            _make_jsonl_event(ts="2026-04-01T10:01:00", session="s1", tool="Read", model="sonnet"),
            _make_jsonl_event(ts="2026-04-01T10:02:00", session="s1", tool="Bash", model="haiku"),
        ]
        _write_jsonl_file(jsonl, events)

        store = ClaudeStorage(db_path=tmp_path / "test.db")
        store.import_from_jsonl(jsonl_path=jsonl)
        breakdown = store.get_model_breakdown()

        models = {row["model"] for row in breakdown}
        assert "sonnet" in models
        assert "haiku" in models

        sonnet_row = next(r for r in breakdown if r["model"] == "sonnet")
        assert sonnet_row["events"] == 2

    def test_export_csv(self, tmp_path: Path) -> None:
        """export_csv should write a valid CSV file with a header and data rows."""
        jsonl = tmp_path / "events.jsonl"
        events = [
            _make_jsonl_event(ts="2026-04-01T10:00:00", session="s1", tool="Edit"),
            _make_jsonl_event(ts="2026-04-01T10:01:00", session="s1", tool="Read"),
        ]
        _write_jsonl_file(jsonl, events)

        store = ClaudeStorage(db_path=tmp_path / "test.db")
        store.import_from_jsonl(jsonl_path=jsonl)

        csv_path = tmp_path / "export.csv"
        count = store.export_csv(csv_path)

        assert count == 2
        assert csv_path.exists()

        with open(csv_path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        assert len(rows) == 2

    def test_empty_database(self, claude_storage: ClaudeStorage) -> None:
        """get_sessions on a fresh database must return an empty list."""
        sessions = claude_storage.get_sessions()
        assert sessions == []
