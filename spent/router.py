"""Smart model router -- automatically redirects calls to optimal models."""

from __future__ import annotations

from .analyzer import classify_prompt, recommend_model, TASK_TYPES
from .pricing import _detect_provider, calculate_cost


class Router:
    """Routes API calls to the optimal model based on task complexity.

    Usage:
        from spent import track
        client = track(OpenAI(), optimize=True)
        # Simple tasks auto-routed to gpt-4o-mini
        # Complex tasks stay on gpt-4o
    """

    _instance: Router | None = None

    def __init__(self, *, enabled: bool = True, min_complexity: int = 5):
        self.enabled = enabled
        # Only downgrade if original model's tier is >= this complexity
        self.min_complexity = min_complexity
        self.reroutes: list[dict] = []
        self._overrides: dict[str, str] = {}  # task_type -> forced model

    @classmethod
    def get(cls) -> Router:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        cls._instance = None

    def override(self, task_type: str, model: str) -> None:
        """Force a specific model for a task type."""
        if task_type not in TASK_TYPES:
            raise ValueError(f"Unknown task type: {task_type}. Valid: {list(TASK_TYPES.keys())}")
        self._overrides[task_type] = model

    def route(self, messages: list[dict], model: str) -> str:
        """Decide the optimal model for this call.

        Returns the model to actually use (may be different from input).
        """
        if not self.enabled:
            return model

        provider = _detect_provider(model)
        if provider is None:
            return model

        classification = classify_prompt(messages)
        task_type = classification["task_type"]
        complexity = classification["complexity"]

        # Check user overrides first
        if task_type in self._overrides:
            chosen = self._overrides[task_type]
            self._record_reroute(model, chosen, task_type, complexity, "user_override")
            return chosen

        # Don't reroute if confidence is too low
        if classification["confidence"] < 0.3:
            return model

        recommended = recommend_model(task_type, provider)
        if recommended is None or recommended == model:
            return model

        # Only downgrade if the task is simpler than the model's tier
        rec_cost = _estimate_relative_cost(recommended)
        cur_cost = _estimate_relative_cost(model)

        if rec_cost < cur_cost:
            self._record_reroute(model, recommended, task_type, complexity, "auto")
            return recommended

        return model

    def _record_reroute(
        self, original: str, routed: str, task_type: str, complexity: int, reason: str
    ) -> None:
        self.reroutes.append({
            "original_model": original,
            "routed_model": routed,
            "task_type": task_type,
            "complexity": complexity,
            "reason": reason,
        })

    def summary(self) -> dict:
        """Return routing summary."""
        if not self.reroutes:
            return {"total_reroutes": 0, "by_task": {}, "estimated_savings": 0.0}

        by_task: dict[str, int] = {}
        for r in self.reroutes:
            by_task[r["task_type"]] = by_task.get(r["task_type"], 0) + 1

        return {
            "total_reroutes": len(self.reroutes),
            "by_task": by_task,
            "reroutes": self.reroutes,
        }


def _estimate_relative_cost(model: str) -> float:
    """Rough relative cost for comparison (not exact USD)."""
    from .pricing import PRICING, _resolve_pricing
    pricing = _resolve_pricing(model)
    if pricing is None:
        return 999.0
    return pricing["output"]
