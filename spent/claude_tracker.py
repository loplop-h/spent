"""Claude Code session cost tracker.

Reads the JSONL hook log (~/.spent/claude-sessions.jsonl) and computes
session metrics -- costs, efficiency, tool breakdown -- without any
external API calls. All estimation is done locally from character counts.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


# -- Immutable configuration -------------------------------------------------

@dataclass(frozen=True)
class ModelPricing:
    """Per-1M-token pricing for a model family."""
    input_usd: float
    output_usd: float


# Claude Code model pricing (per 1M tokens).
MODEL_PRICING: dict[str, ModelPricing] = {
    "opus": ModelPricing(input_usd=15.00, output_usd=75.00),
    "sonnet": ModelPricing(input_usd=3.00, output_usd=15.00),
    "haiku": ModelPricing(input_usd=0.80, output_usd=4.00),
}

# Rough token estimation: ~4 characters = 1 token.
CHARS_PER_TOKEN = 4

# Tools classified by productivity status.
PRODUCTIVE_TOOLS = frozenset({
    "Edit", "Write", "MultiEdit", "Agent",
})

NEUTRAL_TOOLS = frozenset({
    "Read", "Grep", "Glob", "TodoRead", "TodoWrite",
    "TaskCreate", "TaskUpdate", "TaskStatus",
    "ToolSearch", "WebSearch", "WebFetch",
})

# Everything else defaults to context-dependent classification.
# Bash is classified by exit code. Repeated Reads are classified as wasted.


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
            return ToolEvent(
                ts=d.get("ts", ""),
                tool=d.get("tool", ""),
                input_size=int(d.get("input_size", 0)),
                output_size=int(d.get("output_size", 0)),
                session=d.get("session", ""),
                model=d.get("model", "sonnet"),
                event=d.get("event", "tool_use"),
                has_error=bool(d.get("has_error", False)),
                file_path=d.get("file_path", ""),
                output_text=d.get("output_text", ""),
            )
        except (json.JSONDecodeError, TypeError, ValueError):
            return None


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
        events = self._read_events()
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

        Scoring:
        - 100% productive tool use = 100
        - High neutral (search/read) = moderate score
        - High wasted (errors, re-edits) = low score
        """
        eff = session.get("efficiency", {})
        productive = eff.get("productive", 0.0)
        wasted = eff.get("wasted", 0.0)
        neutral = eff.get("neutral", 0.0)

        total = productive + wasted + neutral
        if total == 0:
            return 0.0

        # Weighted formula: productive=1.0, neutral=0.5, wasted=0.0
        score = ((productive * 1.0) + (neutral * 0.5) + (wasted * 0.0)) / total
        return round(score * 100, 1)

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

        # Cost calculation.
        total_cost = 0.0
        total_input_tokens = 0
        total_output_tokens = 0
        by_tool: dict[str, ToolStats] = {}
        timeline: list[dict[str, Any]] = []

        for turn_number, event in enumerate(tool_events):
            input_tokens, output_tokens, cost = self._estimate_cost(
                event, turn_number
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

            # Classify productivity.
            status = self._classify_event(event, turn_number, tool_events)

            timeline.append({
                "ts": event.ts,
                "tool": event.tool,
                "cost": round(cost, 6),
                "status": status,
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

        return {
            "session_id": session_id,
            "started": started,
            "duration_minutes": round(duration_minutes, 1),
            "total_cost": round(total_cost, 6),
            "total_tokens": total_input_tokens + total_output_tokens,
            "tool_uses": len(tool_events),
            "by_tool": by_tool_dict,
            "efficiency": {
                "productive": round(productive_cost, 6),
                "wasted": round(wasted_cost, 6),
                "neutral": round(neutral_cost, 6),
            },
            "timeline": timeline,
        }

    # -- Internal: cost estimation -------------------------------------------

    def _estimate_cost(
        self, event: ToolEvent, turn_number: int
    ) -> tuple[int, int, float]:
        """Estimate tokens and cost for a single tool use.

        Claude Code's real token usage includes system prompt, growing
        conversation context, and tool definitions. We model this as:
          input_tokens = max(char_input / 4, 500) + context_overhead
          output_tokens = char_output / 4
          context_overhead = 500 + (turn_number * 200)

        Returns (input_tokens, output_tokens, cost_usd).
        """
        raw_input = max(event.input_size // CHARS_PER_TOKEN, 500)
        context_overhead = 500 + (turn_number * 200)
        input_tokens = raw_input + context_overhead
        output_tokens = max(event.output_size // CHARS_PER_TOKEN, 50)

        pricing = MODEL_PRICING.get(event.model, MODEL_PRICING["sonnet"])
        input_cost = (input_tokens / 1_000_000) * pricing.input_usd
        output_cost = (output_tokens / 1_000_000) * pricing.output_usd
        cost = input_cost + output_cost

        return (input_tokens, output_tokens, cost)

    # -- Internal: productivity classification -------------------------------

    def _classify_event(
        self,
        event: ToolEvent,
        index: int,
        all_events: list[ToolEvent],
    ) -> str:
        """Classify a tool use as productive, neutral, or wasted.

        Rules:
        - PRODUCTIVE: Edit/Write (code written), Agent (delegation),
          Bash with no error indicators.
        - NEUTRAL: Read, Grep, Glob (information gathering).
        - WASTED: Repeated Read of same file within 60s, Edit of same
          file within 30s of another Edit (revision/fix), Bash with
          error indicators.
        """
        tool = event.tool

        # Check for wasted patterns first (overrides default classification).
        if tool == "Read" and self._is_repeated_read(event, index, all_events):
            return "wasted"

        if tool == "Edit" and self._is_rapid_re_edit(event, index, all_events):
            return "wasted"

        if tool == "Bash" and self._looks_like_error(event):
            return "wasted"

        # Default classification by tool type.
        if tool in PRODUCTIVE_TOOLS:
            return "productive"

        if tool in NEUTRAL_TOOLS:
            return "neutral"

        # Bash without error indicators is productive.
        if tool == "Bash":
            return "productive"

        # Unknown tools default to neutral.
        return "neutral"

    def _is_repeated_read(
        self, event: ToolEvent, index: int, all_events: list[ToolEvent]
    ) -> bool:
        """Check if this Read targets the same file as a recent Read (<60s)."""
        if event.tool != "Read":
            return False

        event_time = self._parse_ts(event.ts)
        if event_time is None:
            return False

        for prev_idx in range(index - 1, max(index - 10, -1), -1):
            prev = all_events[prev_idx]
            if prev.tool != "Read":
                continue
            # Use file_path if available, fall back to input_size matching
            if event.file_path and prev.file_path:
                if event.file_path != prev.file_path:
                    continue
            elif prev.input_size != event.input_size:
                continue
            prev_time = self._parse_ts(prev.ts)
            if prev_time is None:
                continue
            if (event_time - prev_time).total_seconds() < 60:
                return True

        return False

    def _is_rapid_re_edit(
        self, event: ToolEvent, index: int, all_events: list[ToolEvent]
    ) -> bool:
        """Check if this Edit follows another Edit of same file within 30s."""
        if event.tool != "Edit":
            return False

        event_time = self._parse_ts(event.ts)
        if event_time is None:
            return False

        for prev_idx in range(index - 1, max(index - 5, -1), -1):
            prev = all_events[prev_idx]
            if prev.tool != "Edit":
                continue
            # Use file_path if available
            if event.file_path and prev.file_path:
                if event.file_path != prev.file_path:
                    continue
            prev_time = self._parse_ts(prev.ts)
            if prev_time is None:
                continue
            if (event_time - prev_time).total_seconds() < 30:
                return True

        return False

    @staticmethod
    def _looks_like_error(event: ToolEvent) -> bool:
        """Detect errors using has_error flag and output text analysis."""
        # Direct flag from hook (parsed from stderr / tool_response)
        if event.has_error:
            return True
        # Check output text for error keywords
        text = event.output_text.lower()
        if any(kw in text for kw in (
            "error", "traceback", "failed", "exception",
            "command not found", "permission denied", "no such file",
        )):
            return True
        return False

    # -- Internal: time helpers ----------------------------------------------

    @staticmethod
    def _parse_ts(ts: str) -> datetime | None:
        """Parse an ISO 8601 timestamp string."""
        try:
            return datetime.fromisoformat(ts)
        except (ValueError, TypeError):
            return None

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
            "duration_minutes": 0.0,
            "total_cost": 0.0,
            "total_tokens": 0,
            "tool_uses": 0,
            "by_tool": {},
            "efficiency": {
                "productive": 0.0,
                "wasted": 0.0,
                "neutral": 0.0,
            },
            "timeline": [],
        }
