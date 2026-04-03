"""Claude Code session cost tracker.

Reads the JSONL hook log (~/.spent/claude-sessions.jsonl) and computes
session metrics -- costs, efficiency, tool breakdown -- without any
external API calls. All estimation is done locally from character counts.

Delegates cost estimation, event classification, efficiency scoring,
and tip generation to the shared cost_engine module.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from . import cost_engine
from .cost_engine import EventData, normalize_model_name


# -- Data types --------------------------------------------------------------

@dataclass(frozen=True)
class ToolEvent:
    """Single tool-use event parsed from the JSONL log."""
    ts: str
    tool: str
    input_size: int
    output_size: int
    session: str
    model: str
    event: str  # "tool_use", "session_start", "session_end"
    has_error: bool = False
    file_path: str = ""
    output_text: str = ""

    @staticmethod
    def from_line(line: str) -> ToolEvent | None:
        """Parse one JSONL line. Returns None on invalid input."""
        try:
            d = json.loads(line)
            if not isinstance(d, dict):
                return None
            return ToolEvent(
                ts=d.get("ts", ""),
                tool=d.get("tool", ""),
                input_size=int(d.get("input_size", 0)),
                output_size=int(d.get("output_size", 0)),
                session=d.get("session", ""),
                model=normalize_model_name(d.get("model", "sonnet")),
                event=d.get("event", "tool_use"),
                has_error=bool(d.get("has_error", False)),
                file_path=d.get("file_path", ""),
                output_text=d.get("output_text", ""),
            )
        except (json.JSONDecodeError, TypeError, ValueError):
            return None

    def to_event_data(self) -> EventData:
        """Convert to the cost_engine EventData for classification."""
        return EventData(
            tool=self.tool,
            ts=self.ts,
            has_error=self.has_error,
            output_text=self.output_text,
            file_path=self.file_path,
            input_size=self.input_size,
            output_size=self.output_size,
        )


@dataclass
class ToolStats:
    """Aggregated stats for one tool type within a session."""
    count: int = 0
    cost: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0


# -- Core tracker ------------------------------------------------------------

class ClaudeTracker:
    """Tracks Claude Code session costs from hook logs.

    All data is read from the JSONL file at LOG_PATH. No network calls.
    """

    LOG_PATH: Path = Path.home() / ".spent" / "claude-sessions.jsonl"

    def __init__(self, log_path: Path | None = None) -> None:
        self._log_path = log_path or self.LOG_PATH

    # -- Public API ----------------------------------------------------------

    def get_current_session(self) -> dict[str, Any]:
        """Get metrics for the most recent session."""
        events = self._read_events_tail(max_lines=5000)
        if not events:
            return self._empty_session()

        # Find the last session ID.
        last_session = events[-1].session
        session_events = [e for e in events if e.session == last_session]
        return self._build_session_metrics(session_events)

    def get_today_sessions(self) -> list[dict[str, Any]]:
        """Get all sessions from today (UTC)."""
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        events = self._read_events()
        today_events = [e for e in events if e.ts.startswith(today)]
        return self._group_sessions(today_events)

    def get_session_history(self, days: int = 7) -> list[dict[str, Any]]:
        """Get session summaries for the last N days."""
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        cutoff_str = cutoff.strftime("%Y-%m-%dT%H:%M:%S")
        events = self._read_events()
        recent = [e for e in events if e.ts >= cutoff_str]
        return self._group_sessions(recent)

    def get_efficiency_score(self, session: dict[str, Any]) -> float:
        """Calculate a 0-100 efficiency score for a session.

        Delegates to cost_engine.compute_efficiency_score().
        """
        eff = session.get("efficiency", {})
        return cost_engine.compute_efficiency_score(
            productive_cost=eff.get("productive", 0.0),
            neutral_cost=eff.get("neutral", 0.0),
            wasted_cost=eff.get("wasted", 0.0),
        )

    # -- Internal: event I/O -------------------------------------------------

    def _read_events(self) -> list[ToolEvent]:
        """Read all events from the JSONL log file."""
        if not self._log_path.exists():
            return []

        events: list[ToolEvent] = []
        try:
            with open(self._log_path, "r", encoding="utf-8") as f:
                for line in f:
                    stripped = line.strip()
                    if not stripped:
                        continue
                    event = ToolEvent.from_line(stripped)
                    if event is not None:
                        events.append(event)
        except OSError:
            return []

        return events

    def _read_events_tail(self, max_lines: int = 5000) -> list[ToolEvent]:
        """Read the last N lines from the JSONL log for fast tail access.

        Falls back to reading the entire file if it has fewer lines.
        """
        if not self._log_path.exists():
            return []

        try:
            with open(self._log_path, "rb") as f:
                # Seek to the end to get file size.
                f.seek(0, 2)
                file_size = f.tell()

                if file_size == 0:
                    return []

                # Estimate bytes per line (~300 avg for JSONL events).
                # Read more than needed to ensure we get max_lines.
                chunk_size = min(file_size, max_lines * 400)
                f.seek(max(0, file_size - chunk_size))

                # If we didn't seek to the start, skip the first partial line.
                if f.tell() > 0:
                    f.readline()

                raw_lines = f.read().decode("utf-8", errors="replace").splitlines()
        except OSError:
            return []

        # Take only the last max_lines.
        tail_lines = raw_lines[-max_lines:] if len(raw_lines) > max_lines else raw_lines

        events: list[ToolEvent] = []
        for line in tail_lines:
            stripped = line.strip()
            if not stripped:
                continue
            event = ToolEvent.from_line(stripped)
            if event is not None:
                events.append(event)

        return events

    # -- Internal: session building ------------------------------------------

    def _group_sessions(self, events: list[ToolEvent]) -> list[dict[str, Any]]:
        """Group events by session ID and build metrics for each."""
        sessions: dict[str, list[ToolEvent]] = {}
        for e in events:
            sessions.setdefault(e.session, []).append(e)

        return [
            self._build_session_metrics(session_events)
            for session_events in sessions.values()
        ]

    def _build_session_metrics(self, events: list[ToolEvent]) -> dict[str, Any]:
        """Compute full metrics for a list of events in one session."""
        if not events:
            return self._empty_session()

        session_id = events[0].session
        tool_events = [e for e in events if e.event == "tool_use"]

        # Timestamps.
        started = events[0].ts
        ended = events[-1].ts
        duration_minutes = self._duration_minutes(started, ended)

        # Convert ToolEvents to EventData for classification.
        event_data_list = [te.to_event_data() for te in tool_events]

        # Cost calculation.
        total_cost = 0.0
        total_input_tokens = 0
        total_output_tokens = 0
        by_tool: dict[str, ToolStats] = {}
        by_model: dict[str, dict[str, Any]] = {}
        timeline: list[dict[str, Any]] = []

        for turn_number, event in enumerate(tool_events):
            input_tokens, output_tokens, cost = cost_engine.estimate_cost(
                input_size=event.input_size,
                output_size=event.output_size,
                turn_number=turn_number,
                model=event.model,
            )
            total_cost += cost
            total_input_tokens += input_tokens
            total_output_tokens += output_tokens

            # Per-tool aggregation.
            stats = by_tool.setdefault(event.tool, ToolStats())
            stats.count += 1
            stats.cost += cost
            stats.input_tokens += input_tokens
            stats.output_tokens += output_tokens

            # Per-model aggregation.
            model_stats = by_model.setdefault(
                event.model,
                {"count": 0, "cost": 0.0, "input_tokens": 0, "output_tokens": 0},
            )
            model_stats["count"] += 1
            model_stats["cost"] += cost
            model_stats["input_tokens"] += input_tokens
            model_stats["output_tokens"] += output_tokens

            # Classify productivity via cost_engine.
            status = cost_engine.classify_event(
                event=event_data_list[turn_number],
                index=turn_number,
                all_events=event_data_list,
            )

            timeline.append({
                "ts": event.ts,
                "tool": event.tool,
                "cost": round(cost, 6),
                "status": status,
                "file_path": event.file_path,
            })

        # Efficiency breakdown.
        productive_cost = sum(
            t["cost"] for t in timeline if t["status"] == "productive"
        )
        wasted_cost = sum(
            t["cost"] for t in timeline if t["status"] == "wasted"
        )
        neutral_cost = sum(
            t["cost"] for t in timeline if t["status"] == "neutral"
        )

        by_tool_dict = {
            name: {"count": s.count, "cost": round(s.cost, 6)}
            for name, s in sorted(by_tool.items(), key=lambda x: x[1].cost, reverse=True)
        }

        # Efficiency score and tips.
        efficiency_score = cost_engine.compute_efficiency_score(
            productive_cost=productive_cost,
            neutral_cost=neutral_cost,
            wasted_cost=wasted_cost,
        )
        tips = self._generate_tips(by_tool_dict, total_cost, wasted_cost, timeline)

        # Derive date from started timestamp.
        date = started[:10] if len(started) >= 10 else ""

        # Dominant model (most tool uses).
        dominant_model = max(
            by_model, key=lambda m: by_model[m]["count"],
        ) if by_model else "sonnet"

        # Round per-model costs.
        by_model_rounded = {
            m: {**s, "cost": round(s["cost"], 6)}
            for m, s in by_model.items()
        }

        return {
            "session_id": session_id,
            "started": started,
            "date": date,
            "duration_minutes": round(duration_minutes, 1),
            "total_cost": round(total_cost, 6),
            "total_tokens": total_input_tokens + total_output_tokens,
            "total_input_tokens": total_input_tokens,
            "total_output_tokens": total_output_tokens,
            "model": dominant_model,
            "by_model": by_model_rounded,
            "tool_uses": len(tool_events),
            "by_tool": by_tool_dict,
            "efficiency": {
                "productive": round(productive_cost, 6),
                "wasted": round(wasted_cost, 6),
                "neutral": round(neutral_cost, 6),
            },
            "efficiency_score": efficiency_score,
            "tips": tips,
            "timeline": timeline,
        }

    # -- Internal: tips generation -------------------------------------------

    @staticmethod
    def _generate_tips(
        by_tool: dict[str, dict],
        total_cost: float,
        wasted_cost: float,
        timeline: list[dict[str, Any]],
    ) -> list[str]:
        """Delegate tip generation to cost_engine."""
        return cost_engine.generate_tips(
            by_tool=by_tool,
            total_cost=total_cost,
            wasted_cost=wasted_cost,
            timeline=timeline,
        )

    # -- Internal: time helpers ----------------------------------------------

    @staticmethod
    def _duration_minutes(start: str, end: str) -> float:
        """Compute duration in minutes between two ISO timestamps."""
        try:
            t_start = datetime.fromisoformat(start)
            t_end = datetime.fromisoformat(end)
            return (t_end - t_start).total_seconds() / 60.0
        except (ValueError, TypeError):
            return 0.0

    @staticmethod
    def _empty_session() -> dict[str, Any]:
        """Return an empty session metrics dict."""
        return {
            "session_id": "",
            "started": "",
            "date": "",
            "duration_minutes": 0.0,
            "total_cost": 0.0,
            "total_tokens": 0,
            "total_input_tokens": 0,
            "total_output_tokens": 0,
            "model": "sonnet",
            "by_model": {},
            "tool_uses": 0,
            "by_tool": {},
            "efficiency": {
                "productive": 0.0,
                "wasted": 0.0,
                "neutral": 0.0,
            },
            "efficiency_score": 0.0,
            "tips": [],
            "timeline": [],
        }
