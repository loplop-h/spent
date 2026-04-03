"""SQLite storage for API call records. Zero external dependencies."""

from __future__ import annotations

import csv
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_DB_PATH = Path.home() / ".spent" / "data.db"
DEFAULT_JSONL_PATH = Path.home() / ".spent" / "claude-sessions.jsonl"


class Storage:
    def __init__(self, db_path: Path | None = None):
        self.db_path = db_path or DEFAULT_DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS requests (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    model TEXT NOT NULL,
                    input_tokens INTEGER NOT NULL,
                    output_tokens INTEGER NOT NULL,
                    cost REAL NOT NULL,
                    duration_ms INTEGER,
                    tags TEXT,
                    endpoint TEXT
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_session
                ON requests(session_id)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_timestamp
                ON requests(timestamp)
            """)

    def record(
        self,
        session_id: str,
        provider: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        cost: float,
        duration_ms: int | None = None,
        tags: list[str] | None = None,
        endpoint: str | None = None,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO requests
                   (timestamp, session_id, provider, model,
                    input_tokens, output_tokens, cost,
                    duration_ms, tags, endpoint)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    datetime.now(timezone.utc).isoformat(),
                    session_id,
                    provider,
                    model,
                    input_tokens,
                    output_tokens,
                    cost,
                    duration_ms,
                    json.dumps(tags) if tags else None,
                    endpoint,
                ),
            )

    def get_session(self, session_id: str) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM requests WHERE session_id = ? ORDER BY timestamp",
                (session_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    def get_sessions(self, limit: int = 50) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT session_id,
                          COUNT(*) as calls,
                          SUM(cost) as total_cost,
                          SUM(input_tokens) as total_input,
                          SUM(output_tokens) as total_output,
                          MIN(timestamp) as started,
                          MAX(timestamp) as ended
                   FROM requests
                   GROUP BY session_id
                   ORDER BY started DESC
                   LIMIT ?""",
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]

    def get_today(self) -> list[dict]:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM requests WHERE timestamp >= ? ORDER BY timestamp",
                (today,),
            ).fetchall()
            return [dict(r) for r in rows]

    def get_range(self, start: str, end: str) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT * FROM requests
                   WHERE timestamp >= ? AND timestamp <= ?
                   ORDER BY timestamp""",
                (start, end),
            ).fetchall()
            return [dict(r) for r in rows]

    def get_total_cost(self) -> float:
        with self._connect() as conn:
            row = conn.execute("SELECT COALESCE(SUM(cost), 0) FROM requests").fetchone()
            return row[0]


# ---------------------------------------------------------------------------
# Claude Code session storage
# ---------------------------------------------------------------------------

class ClaudeStorage:
    """SQLite storage for Claude Code hook events."""

    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = db_path or DEFAULT_DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS claude_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    tool TEXT,
                    model TEXT,
                    input_size INTEGER,
                    output_size INTEGER,
                    input_tokens INTEGER,
                    output_tokens INTEGER,
                    cost REAL,
                    has_error INTEGER DEFAULT 0,
                    file_path TEXT,
                    output_text TEXT,
                    project TEXT,
                    status TEXT
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_claude_session
                ON claude_events(session_id)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_claude_timestamp
                ON claude_events(timestamp)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_claude_project
                ON claude_events(project)
            """)

    def import_from_jsonl(
        self,
        jsonl_path: Path | None = None,
        project: str | None = None,
    ) -> int:
        """Import events from JSONL log into SQLite.

        Returns the number of events imported.
        Skips duplicates based on (timestamp, session_id, tool).
        """
        from . import cost_engine
        from .cost_engine import EventData, normalize_model_name

        path = jsonl_path or DEFAULT_JSONL_PATH
        if not path.exists():
            return 0

        imported = 0
        turn_counters: dict[str, int] = {}

        with self._connect() as conn:
            for line in path.read_text(encoding="utf-8").splitlines():
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    d = json.loads(stripped)
                except (json.JSONDecodeError, TypeError):
                    continue
                if not isinstance(d, dict):
                    continue

                ts = d.get("ts", "")
                event_type = d.get("event", "tool_use")
                session_id = d.get("session", "")
                tool = d.get("tool", "")
                model = normalize_model_name(d.get("model", "sonnet"))
                input_size = int(d.get("input_size", 0))
                output_size = int(d.get("output_size", 0))
                has_error = 1 if d.get("has_error") else 0
                file_path = d.get("file_path", "")
                output_text = d.get("output_text", "")

                # Skip non-tool events for cost calculation.
                input_tokens = 0
                output_tokens = 0
                event_cost = 0.0
                status = ""

                if event_type == "tool_use" and tool:
                    turn = turn_counters.get(session_id, 0)
                    turn_counters[session_id] = turn + 1

                    input_tokens, output_tokens, event_cost = (
                        cost_engine.estimate_cost(
                            input_size=input_size,
                            output_size=output_size,
                            turn_number=turn,
                            model=model,
                        )
                    )
                    ed = EventData(
                        tool=tool,
                        ts=ts,
                        has_error=bool(has_error),
                        output_text=output_text,
                        file_path=file_path,
                        input_size=input_size,
                        output_size=output_size,
                    )
                    # Build minimal event list for classification context.
                    status = cost_engine.classify_event(ed, 0, [ed])

                # Check for duplicate.
                existing = conn.execute(
                    """SELECT 1 FROM claude_events
                       WHERE timestamp = ? AND session_id = ? AND tool = ?
                       LIMIT 1""",
                    (ts, session_id, tool),
                ).fetchone()
                if existing:
                    continue

                conn.execute(
                    """INSERT INTO claude_events
                       (timestamp, event_type, session_id, tool, model,
                        input_size, output_size, input_tokens, output_tokens,
                        cost, has_error, file_path, output_text, project, status)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        ts, event_type, session_id, tool, model,
                        input_size, output_size, input_tokens, output_tokens,
                        round(event_cost, 8), has_error, file_path,
                        output_text, project or "", status,
                    ),
                )
                imported += 1

        return imported

    def get_sessions(
        self,
        project: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Get session summaries, optionally filtered by project."""
        with self._connect() as conn:
            if project:
                rows = conn.execute(
                    """SELECT session_id,
                              COUNT(*) as events,
                              SUM(cost) as total_cost,
                              SUM(input_tokens) as total_input,
                              SUM(output_tokens) as total_output,
                              MIN(timestamp) as started,
                              MAX(timestamp) as ended,
                              model
                       FROM claude_events
                       WHERE project = ? AND event_type = 'tool_use'
                       GROUP BY session_id
                       ORDER BY started DESC LIMIT ?""",
                    (project, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    """SELECT session_id,
                              COUNT(*) as events,
                              SUM(cost) as total_cost,
                              SUM(input_tokens) as total_input,
                              SUM(output_tokens) as total_output,
                              MIN(timestamp) as started,
                              MAX(timestamp) as ended,
                              model
                       FROM claude_events
                       WHERE event_type = 'tool_use'
                       GROUP BY session_id
                       ORDER BY started DESC LIMIT ?""",
                    (limit,),
                ).fetchall()
            return [dict(r) for r in rows]

    def get_session(self, session_id: str) -> list[dict[str, Any]]:
        """Get all events for a single session."""
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT * FROM claude_events
                   WHERE session_id = ? ORDER BY timestamp""",
                (session_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    def get_model_breakdown(
        self,
        project: str | None = None,
    ) -> list[dict[str, Any]]:
        """Get aggregated cost breakdown by model."""
        with self._connect() as conn:
            query = """SELECT model,
                              COUNT(*) as events,
                              SUM(cost) as total_cost,
                              SUM(input_tokens) as total_input,
                              SUM(output_tokens) as total_output
                       FROM claude_events
                       WHERE event_type = 'tool_use'"""
            params: list[Any] = []
            if project:
                query += " AND project = ?"
                params.append(project)
            query += " GROUP BY model ORDER BY total_cost DESC"
            rows = conn.execute(query, params).fetchall()
            return [dict(r) for r in rows]

    def export_csv(
        self,
        output_path: Path,
        project: str | None = None,
    ) -> int:
        """Export events to CSV. Returns number of rows exported."""
        with self._connect() as conn:
            query = "SELECT * FROM claude_events WHERE event_type = 'tool_use'"
            params: list[Any] = []
            if project:
                query += " AND project = ?"
                params.append(project)
            query += " ORDER BY timestamp"
            rows = conn.execute(query, params).fetchall()

            if not rows:
                return 0

            columns = rows[0].keys()
            with open(output_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=columns)
                writer.writeheader()
                for row in rows:
                    writer.writerow(dict(row))

            return len(rows)
