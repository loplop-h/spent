"""SQLite storage for API call records. Zero external dependencies."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_DB_PATH = Path.home() / ".spent" / "data.db"


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
