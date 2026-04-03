"""Shared cost estimation and event classification engine.

Single source of truth for all cost calculations and productivity
classification across claude_tracker, tui, and claude_web modules.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


# ── Cost model constants ────────────────────────────────────────────

CHARS_PER_TOKEN = 4
BASE_OVERHEAD_TOKENS = 500   # system prompt + tool definitions
CONTEXT_GROWTH_PER_TURN = 200  # context grows each turn
MIN_INPUT_TOKENS = 500
MIN_OUTPUT_TOKENS = 50


@dataclass(frozen=True)
class ModelPricing:
    input_per_million: float
    output_per_million: float


MODEL_PRICING: dict[str, ModelPricing] = {
    "opus": ModelPricing(15.00, 75.00),
    "sonnet": ModelPricing(3.00, 15.00),
    "haiku": ModelPricing(0.80, 4.00),
}

DEFAULT_MODEL = "sonnet"

_MODEL_PREFIXES: tuple[tuple[str, str], ...] = (
    ("claude-opus", "opus"),
    ("claude-sonnet", "sonnet"),
    ("claude-haiku", "haiku"),
    ("claude-3-opus", "opus"),
    ("claude-3-5-sonnet", "sonnet"),
    ("claude-3-sonnet", "sonnet"),
    ("claude-3-5-haiku", "haiku"),
    ("claude-3-haiku", "haiku"),
)

_SHORT_NAMES = frozenset(MODEL_PRICING.keys())


def normalize_model_name(raw: str) -> str:
    """Map a full Claude model ID to its short family name.

    Examples:
        "claude-sonnet-4-6"          -> "sonnet"
        "claude-opus-4-6"            -> "opus"
        "claude-haiku-4-5-20251001"  -> "haiku"
        "sonnet"                     -> "sonnet"  (pass-through)
        ""                           -> "sonnet"  (default)
    """
    if not raw:
        return DEFAULT_MODEL
    if raw in _SHORT_NAMES:
        return raw
    lower = raw.lower()
    for prefix, family in _MODEL_PREFIXES:
        if lower.startswith(prefix):
            return family
    return DEFAULT_MODEL


# ── Classification constants ────────────────────────────────────────

PRODUCTIVE_TOOLS = frozenset({
    "Edit", "Write", "MultiEdit", "NotebookEdit", "Agent",
})

NEUTRAL_TOOLS = frozenset({
    "Read", "Grep", "Glob", "TaskCreate", "TaskUpdate", "TaskGet",
    "TaskList", "TaskStop", "TodoRead", "TodoWrite", "ToolSearch",
    "WebSearch", "WebFetch", "AskUserQuestion",
})

ERROR_KEYWORDS = frozenset({
    "error", "traceback", "failed", "exception",
    "command not found", "permission denied", "no such file",
    "module not found", "syntax error", "exit code 1",
})

REPEATED_READ_WINDOW_SEC = 60
RAPID_RE_EDIT_WINDOW_SEC = 30


# ── Cost estimation ─────────────────────────────────────────────────

def estimate_cost(
    input_size: int,
    output_size: int,
    turn_number: int,
    model: str = DEFAULT_MODEL,
) -> tuple[int, int, float]:
    """Estimate tokens and cost for a single tool use.

    Args:
        input_size: Character count of tool input.
        output_size: Character count of tool output.
        turn_number: 0-indexed position in the session (for context growth).
        model: Model family name (opus/sonnet/haiku).

    Returns:
        (input_tokens, output_tokens, cost_usd)
    """
    raw_input = max(input_size // CHARS_PER_TOKEN, MIN_INPUT_TOKENS)
    context_overhead = BASE_OVERHEAD_TOKENS + (turn_number * CONTEXT_GROWTH_PER_TURN)
    input_tokens = raw_input + context_overhead
    output_tokens = max(output_size // CHARS_PER_TOKEN, MIN_OUTPUT_TOKENS)

    pricing = MODEL_PRICING.get(model, MODEL_PRICING[DEFAULT_MODEL])
    cost = (
        (input_tokens / 1_000_000) * pricing.input_per_million
        + (output_tokens / 1_000_000) * pricing.output_per_million
    )

    return (input_tokens, output_tokens, round(cost, 8))


# ── Event classification ────────────────────────────────────────────

@dataclass(frozen=True)
class EventData:
    """Minimal event data needed for classification."""
    tool: str
    ts: str = ""
    has_error: bool = False
    output_text: str = ""
    file_path: str = ""
    input_size: int = 0
    output_size: int = 0


def classify_event(
    event: EventData,
    index: int,
    all_events: list[EventData],
) -> str:
    """Classify a tool use as productive, neutral, or wasted.

    Returns: "productive", "neutral", or "wasted"
    """
    tool = event.tool

    # Wasted checks (highest priority)
    if tool == "Bash" and _is_error(event):
        return "wasted"
    if tool == "Read" and _is_repeated_read(event, index, all_events):
        return "wasted"
    if tool == "Edit" and _is_rapid_re_edit(event, index, all_events):
        return "wasted"

    # Productive tools
    if tool in PRODUCTIVE_TOOLS:
        return "productive"

    # Neutral tools
    if tool in NEUTRAL_TOOLS:
        return "neutral"

    # Bash without error = productive
    if tool == "Bash":
        return "productive"

    return "neutral"


def compute_efficiency_score(
    productive_cost: float,
    neutral_cost: float,
    wasted_cost: float,
) -> float:
    """Compute 0-100 efficiency score.

    Formula: (productive * 1.0 + neutral * 0.5 + wasted * 0.0) / total * 100
    """
    total = productive_cost + neutral_cost + wasted_cost
    if total <= 0:
        return 0.0
    score = ((productive_cost * 1.0) + (neutral_cost * 0.5)) / total
    return round(score * 100, 1)


def generate_tips(
    by_tool: dict[str, dict],
    total_cost: float,
    wasted_cost: float,
    timeline: list[dict],
) -> list[str]:
    """Generate actionable efficiency tips from session data."""
    tips = []

    if wasted_cost > 0:
        tips.append(f"${wasted_cost:.4f} wasted on failed/repeated actions")

    # Most expensive tool
    if by_tool:
        top_tool = max(by_tool.items(), key=lambda x: x[1].get("cost", 0))
        if total_cost > 0 and top_tool[1].get("cost", 0) > total_cost * 0.4:
            pct = int(top_tool[1]["cost"] / total_cost * 100)
            tips.append(f"{top_tool[0]} is {pct}% of your spend (${top_tool[1]['cost']:.4f})")

    # Count wasted events
    wasted_events = [t for t in timeline if t.get("status") == "wasted"]
    if len(wasted_events) >= 3:
        tips.append(f"{len(wasted_events)} actions classified as wasted -- check failed commands")

    # Detect repeated reads
    read_files: dict[str, int] = {}
    for t in timeline:
        if t.get("tool") == "Read" and t.get("file_path"):
            read_files[t["file_path"]] = read_files.get(t["file_path"], 0) + 1
    for fp, count in read_files.items():
        if count >= 3:
            short = fp.split("/")[-1] if "/" in fp else fp.split("\\")[-1] if "\\" in fp else fp
            tips.append(f"Read {short} {count} times -- consider keeping it open")

    return tips


# ── Internal helpers ────────────────────────────────────────────────

def _is_error(event: EventData) -> bool:
    if event.has_error:
        return True
    text = event.output_text.lower()
    return any(kw in text for kw in ERROR_KEYWORDS)


def _is_repeated_read(event: EventData, index: int, all_events: list[EventData]) -> bool:
    event_time = _parse_ts(event.ts)
    if event_time is None:
        return False

    for prev_idx in range(index - 1, max(index - 10, -1), -1):
        prev = all_events[prev_idx]
        if prev.tool != "Read":
            continue
        # Match by file_path if available, else by input_size
        if event.file_path and prev.file_path:
            if event.file_path != prev.file_path:
                continue
        elif prev.input_size != event.input_size:
            continue
        prev_time = _parse_ts(prev.ts)
        if prev_time is None:
            continue
        if (event_time - prev_time).total_seconds() < REPEATED_READ_WINDOW_SEC:
            return True
    return False


def _is_rapid_re_edit(event: EventData, index: int, all_events: list[EventData]) -> bool:
    event_time = _parse_ts(event.ts)
    if event_time is None:
        return False

    for prev_idx in range(index - 1, max(index - 5, -1), -1):
        prev = all_events[prev_idx]
        if prev.tool != "Edit":
            continue
        if event.file_path and prev.file_path and event.file_path != prev.file_path:
            continue
        prev_time = _parse_ts(prev.ts)
        if prev_time is None:
            continue
        if (event_time - prev_time).total_seconds() < RAPID_RE_EDIT_WINDOW_SEC:
            return True
    return False


def _parse_ts(ts: str) -> datetime | None:
    try:
        return datetime.fromisoformat(ts)
    except (ValueError, TypeError):
        return None
