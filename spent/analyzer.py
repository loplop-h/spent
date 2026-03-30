"""Prompt analyzer -- classifies API calls by task type and complexity."""

from __future__ import annotations

import re

# Task types ordered by complexity (simple -> complex)
TASK_TYPES = {
    "yes_no": {"complexity": 1, "description": "Yes/no or true/false questions"},
    "classification": {"complexity": 1, "description": "Categorizing into predefined labels"},
    "extraction": {"complexity": 2, "description": "Extracting specific data from text"},
    "sentiment": {"complexity": 1, "description": "Sentiment analysis"},
    "translation": {"complexity": 3, "description": "Translating between languages"},
    "summarization": {"complexity": 3, "description": "Condensing text"},
    "rewriting": {"complexity": 3, "description": "Rephrasing or reformatting text"},
    "qa": {"complexity": 4, "description": "Answering questions about given context"},
    "generation": {"complexity": 5, "description": "Creating new content from scratch"},
    "reasoning": {"complexity": 7, "description": "Logic, math, multi-step problems"},
    "coding": {"complexity": 8, "description": "Writing or debugging code"},
    "analysis": {"complexity": 6, "description": "Deep analysis requiring nuance"},
    "unknown": {"complexity": 5, "description": "Could not determine task type"},
}

# Complexity -> recommended model tier
MODEL_TIERS: dict[str, dict[str, str]] = {
    "openai": {
        "low": "gpt-4o-mini",       # complexity 1-2
        "medium": "gpt-4o-mini",     # complexity 3-4
        "high": "gpt-4o",            # complexity 5-6
        "max": "o3",                 # complexity 7-8
    },
    "anthropic": {
        "low": "claude-haiku-4-5",
        "medium": "claude-haiku-4-5",
        "high": "claude-sonnet-4-6",
        "max": "claude-opus-4-6",
    },
    "google": {
        "low": "gemini-2.0-flash-lite",
        "medium": "gemini-2.5-flash",
        "high": "gemini-2.5-pro",
        "max": "gemini-2.5-pro",
    },
}

# Patterns for task detection
_PATTERNS: list[tuple[str, list[str]]] = [
    ("yes_no", [
        r"\b(yes or no|true or false|is it|does it|can you confirm)\b",
        r"\b(answer with (yes|no|true|false))\b",
        r"\b(one word only|single word)\b.*\b(yes|no|positive|negative)\b",
    ]),
    ("classification", [
        r"\b(classify|categorize|categorise|label|which category)\b",
        r"\b(assign.*(label|category|class))\b",
        r"\b(is this.*(spam|positive|negative|urgent))\b",
        r"\b(rate.*(1|2|3|4|5|sentiment|score))\b",
    ]),
    ("extraction", [
        r"\b(extract|pull out|find all|list all|get the)\b.*\b(from|in)\b",
        r"\b(keywords?|entities|names?|emails?|numbers?|dates?)\b.*\b(from|in)\b",
        r"\b(parse|scrape)\b",
    ]),
    ("sentiment", [
        r"\b(sentiment|mood|tone|feeling)\b",
        r"\b(positive|negative|neutral)\b.*\b(text|review|comment)\b",
    ]),
    ("translation", [
        r"\b(translat|traduc)\b",
        r"\b(in (spanish|french|german|japanese|chinese|korean|portuguese|italian))\b",
        r"\b(to (spanish|french|german|japanese|chinese|korean|portuguese|italian))\b",
    ]),
    ("summarization", [
        r"\b(summarize|summarise|summary|tldr|tl;dr|condense|brief)\b",
        r"\b(in (one|two|three|a few) sentences?)\b",
    ]),
    ("rewriting", [
        r"\b(rewrite|rephrase|paraphrase|reformulat|simplify this)\b",
        r"\b(make.*(shorter|longer|simpler|formal|casual))\b",
    ]),
    ("qa", [
        r"\b(based on|according to|given the|from the (text|context|document))\b",
        r"\b(answer.*question.*about)\b",
    ]),
    ("coding", [
        r"\b(write.*(code|function|script|program|class|module))\b",
        r"\b(debug|fix.*(bug|error|issue)|refactor)\b",
        r"\b(implement|algorithm|api endpoint)\b",
        r"```",
    ]),
    ("reasoning", [
        r"\b(step by step|think through|reason|logic|proof|calculate)\b",
        r"\b(why does|explain why|how would you|what if)\b",
        r"\b(compare and contrast|pros and cons|trade.?offs?)\b",
    ]),
    ("analysis", [
        r"\b(analyze|analyse|evaluate|assess|review|critique)\b",
        r"\b(what are the implications|in depth)\b",
    ]),
    ("generation", [
        r"\b(write|create|generate|compose|draft)\b.*\b(blog|article|essay|story|email|post)\b",
        r"\b(come up with|brainstorm|ideate)\b",
    ]),
]


def classify_prompt(messages: list[dict]) -> dict:
    """Classify a prompt by task type and complexity.

    Args:
        messages: OpenAI-format messages list [{"role": ..., "content": ...}]

    Returns:
        {"task_type": str, "complexity": int (1-8), "description": str,
         "confidence": float (0-1)}
    """
    text = _extract_text(messages).lower()

    if not text:
        return _make_result("unknown", 0.0)

    scores: dict[str, float] = {}
    for task_type, patterns in _PATTERNS:
        score = 0.0
        for pattern in patterns:
            matches = re.findall(pattern, text, re.IGNORECASE)
            score += len(matches) * 1.0
        if score > 0:
            scores[task_type] = score

    if not scores:
        # Fallback heuristics
        if len(text) < 100:
            return _make_result("classification", 0.3)
        return _make_result("unknown", 0.2)

    best = max(scores, key=scores.get)
    total = sum(scores.values())
    confidence = min(scores[best] / max(total, 1), 1.0)

    return _make_result(best, confidence)


def recommend_model(task_type: str, provider: str) -> str | None:
    """Recommend optimal model for a task type and provider."""
    tiers = MODEL_TIERS.get(provider)
    if tiers is None:
        return None

    complexity = TASK_TYPES.get(task_type, {}).get("complexity", 5)

    if complexity <= 2:
        return tiers["low"]
    elif complexity <= 4:
        return tiers["medium"]
    elif complexity <= 6:
        return tiers["high"]
    else:
        return tiers["max"]


def analyze_session(records: list[dict]) -> list[dict]:
    """Analyze a session's records and produce optimization recommendations.

    Returns a list of recommendations:
        [{"call_index": int, "current_model": str, "recommended_model": str,
          "task_type": str, "current_cost": float, "optimized_cost": float,
          "savings": float, "reason": str}]
    """
    from .pricing import calculate_cost, _detect_provider

    recommendations = []

    for i, record in enumerate(records):
        messages = record.get("_messages")
        if messages is None:
            continue

        classification = classify_prompt(messages)
        task_type = classification["task_type"]
        provider = _detect_provider(record["model"])

        if provider is None:
            continue

        recommended = recommend_model(task_type, provider)
        if recommended is None or recommended == record["model"]:
            continue

        current_cost = record["cost"]
        optimized_cost = calculate_cost(
            recommended,
            record["input_tokens"],
            record["output_tokens"],
        )

        if optimized_cost >= current_cost:
            continue

        savings = current_cost - optimized_cost
        if savings < 0.0001:
            continue

        recommendations.append({
            "call_index": i,
            "current_model": record["model"],
            "recommended_model": recommended,
            "task_type": task_type,
            "task_description": TASK_TYPES[task_type]["description"],
            "complexity": classification["complexity"],
            "confidence": classification["confidence"],
            "current_cost": current_cost,
            "optimized_cost": optimized_cost,
            "savings": round(savings, 6),
            "reason": (
                f"{task_type} (complexity {classification['complexity']}/8) "
                f"doesn't need {record['model']}. "
                f"Use {recommended} and save ${savings:.4f}."
            ),
        })

    return recommendations


def _extract_text(messages: list[dict]) -> str:
    """Extract user message text from messages list."""
    parts = []
    for msg in messages:
        if msg.get("role") == "user":
            content = msg.get("content", "")
            if isinstance(content, str):
                parts.append(content)
            elif isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        parts.append(block.get("text", ""))
    return " ".join(parts)


def _make_result(task_type: str, confidence: float) -> dict:
    info = TASK_TYPES.get(task_type, TASK_TYPES["unknown"])
    return {
        "task_type": task_type,
        "complexity": info["complexity"],
        "description": info["description"],
        "confidence": round(confidence, 2),
    }
