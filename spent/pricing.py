"""Model pricing database (per 1M tokens, USD). Updated March 2026."""

from __future__ import annotations

# {model_name: {"input": price_per_1M, "output": price_per_1M}}
PRICING: dict[str, dict[str, float]] = {
    # OpenAI
    "gpt-4o": {"input": 2.50, "output": 10.00},
    "gpt-4o-2024-11-20": {"input": 2.50, "output": 10.00},
    "gpt-4o-2024-08-06": {"input": 2.50, "output": 10.00},
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
    "gpt-4o-mini-2024-07-18": {"input": 0.15, "output": 0.60},
    "gpt-4-turbo": {"input": 10.00, "output": 30.00},
    "gpt-4-turbo-2024-04-09": {"input": 10.00, "output": 30.00},
    "gpt-4": {"input": 30.00, "output": 60.00},
    "gpt-4-0613": {"input": 30.00, "output": 60.00},
    "gpt-3.5-turbo": {"input": 0.50, "output": 1.50},
    "gpt-3.5-turbo-0125": {"input": 0.50, "output": 1.50},
    "o1": {"input": 15.00, "output": 60.00},
    "o1-2024-12-17": {"input": 15.00, "output": 60.00},
    "o1-mini": {"input": 3.00, "output": 12.00},
    "o1-mini-2024-09-12": {"input": 3.00, "output": 12.00},
    "o3": {"input": 10.00, "output": 40.00},
    "o3-mini": {"input": 1.10, "output": 4.40},
    "o3-mini-2025-01-31": {"input": 1.10, "output": 4.40},
    "o4-mini": {"input": 1.10, "output": 4.40},
    # Anthropic
    "claude-opus-4-6": {"input": 15.00, "output": 75.00},
    "claude-opus-4-5-20250620": {"input": 15.00, "output": 75.00},
    "claude-sonnet-4-6": {"input": 3.00, "output": 15.00},
    "claude-sonnet-4-5-20250514": {"input": 3.00, "output": 15.00},
    "claude-haiku-4-5": {"input": 0.80, "output": 4.00},
    "claude-haiku-4-5-20251001": {"input": 0.80, "output": 4.00},
    "claude-3-5-sonnet-20241022": {"input": 3.00, "output": 15.00},
    "claude-3-5-haiku-20241022": {"input": 0.80, "output": 4.00},
    "claude-3-opus-20240229": {"input": 15.00, "output": 75.00},
    "claude-3-sonnet-20240229": {"input": 3.00, "output": 15.00},
    "claude-3-haiku-20240307": {"input": 0.25, "output": 1.25},
    # Google
    "gemini-2.5-pro": {"input": 1.25, "output": 10.00},
    "gemini-2.5-flash": {"input": 0.15, "output": 0.60},
    "gemini-2.0-flash": {"input": 0.10, "output": 0.40},
    "gemini-2.0-flash-lite": {"input": 0.075, "output": 0.30},
    "gemini-1.5-pro": {"input": 1.25, "output": 5.00},
    "gemini-1.5-flash": {"input": 0.075, "output": 0.30},
    # DeepSeek
    "deepseek-chat": {"input": 0.27, "output": 1.10},
    "deepseek-reasoner": {"input": 0.55, "output": 2.19},
    # Mistral
    "mistral-large-latest": {"input": 2.00, "output": 6.00},
    "mistral-small-latest": {"input": 0.10, "output": 0.30},
    "codestral-latest": {"input": 0.30, "output": 0.90},
    # Groq (hosted)
    "llama-3.3-70b-versatile": {"input": 0.59, "output": 0.79},
    "llama-3.1-8b-instant": {"input": 0.05, "output": 0.08},
    "mixtral-8x7b-32768": {"input": 0.24, "output": 0.24},
}

# Provider -> list of models, cheapest first
PROVIDER_MODELS: dict[str, list[str]] = {
    "openai": [
        "gpt-4o-mini", "gpt-3.5-turbo", "o3-mini", "o4-mini",
        "gpt-4o", "o1-mini", "gpt-4-turbo", "o3", "o1", "gpt-4",
    ],
    "anthropic": [
        "claude-3-haiku-20240307", "claude-haiku-4-5",
        "claude-sonnet-4-6", "claude-opus-4-6",
    ],
    "google": [
        "gemini-2.0-flash-lite", "gemini-1.5-flash", "gemini-2.5-flash",
        "gemini-2.0-flash", "gemini-1.5-pro", "gemini-2.5-pro",
    ],
}


def calculate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    """Calculate cost in USD for a single API call."""
    pricing = _resolve_pricing(model)
    if pricing is None:
        return 0.0
    input_cost = (input_tokens / 1_000_000) * pricing["input"]
    output_cost = (output_tokens / 1_000_000) * pricing["output"]
    return round(input_cost + output_cost, 6)


def get_cheaper_alternative(model: str) -> tuple[str, float] | None:
    """Return (cheaper_model, savings_ratio) or None if already cheapest."""
    pricing = _resolve_pricing(model)
    if pricing is None:
        return None

    current_output = pricing["output"]
    provider = _detect_provider(model)
    if provider is None:
        return None

    candidates = PROVIDER_MODELS.get(provider, [])
    for candidate in candidates:
        candidate_pricing = PRICING.get(candidate)
        if candidate_pricing and candidate_pricing["output"] < current_output:
            savings = 1.0 - (candidate_pricing["output"] / current_output)
            return (candidate, round(savings, 2))

    return None


def _resolve_pricing(model: str) -> dict[str, float] | None:
    """Look up pricing, trying exact match then prefix match."""
    if model in PRICING:
        return PRICING[model]
    for key in PRICING:
        if model.startswith(key) or key.startswith(model):
            return PRICING[key]
    return None


def _detect_provider(model: str) -> str | None:
    """Detect provider from model name."""
    if model.startswith(("gpt-", "o1", "o3", "o4")):
        return "openai"
    if model.startswith("claude"):
        return "anthropic"
    if model.startswith("gemini"):
        return "google"
    if model.startswith("deepseek"):
        return "deepseek"
    if model.startswith(("mistral", "codestral")):
        return "mistral"
    if model.startswith(("llama", "mixtral")):
        return "groq"
    return None
