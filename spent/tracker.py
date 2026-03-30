"""Core tracker -- singleton that records every LLM API call."""

from __future__ import annotations

import atexit
import time
import uuid

from .pricing import calculate_cost, get_cheaper_alternative
from .storage import Storage


class CallRecord:
    __slots__ = (
        "provider", "model", "input_tokens", "output_tokens",
        "cost", "duration_ms", "timestamp",
    )

    def __init__(
        self,
        provider: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        cost: float,
        duration_ms: int | None = None,
    ):
        self.provider = provider
        self.model = model
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.cost = cost
        self.duration_ms = duration_ms
        self.timestamp = time.time()


class Tracker:
    """Global tracker singleton. Use Tracker.get() to access."""

    _instance: Tracker | None = None

    def __init__(self, *, quiet: bool = False) -> None:
        self.session_id = uuid.uuid4().hex[:8]
        self.storage = Storage()
        self.records: list[CallRecord] = []
        self.quiet = quiet
        self._start = time.time()
        self._budget: float | None = None
        self._budget_warned = False

    @classmethod
    def get(cls) -> Tracker:
        if cls._instance is None:
            cls._instance = cls()
            atexit.register(cls._instance._on_exit)
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        cls._instance = None

    def set_budget(self, usd: float) -> None:
        self._budget = usd
        self._budget_warned = False

    def record(
        self,
        provider: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        duration_ms: int | None = None,
    ) -> float:
        cost = calculate_cost(model, input_tokens, output_tokens)

        rec = CallRecord(
            provider=provider,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost=cost,
            duration_ms=duration_ms,
        )
        self.records.append(rec)

        self.storage.record(
            session_id=self.session_id,
            provider=provider,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost=cost,
            duration_ms=duration_ms,
        )

        self._check_budget()
        return cost

    def summary(self) -> dict:
        total_cost = sum(r.cost for r in self.records)
        total_input = sum(r.input_tokens for r in self.records)
        total_output = sum(r.output_tokens for r in self.records)

        by_model: dict[str, dict] = {}
        for r in self.records:
            if r.model not in by_model:
                by_model[r.model] = {
                    "cost": 0.0,
                    "calls": 0,
                    "input_tokens": 0,
                    "output_tokens": 0,
                }
            entry = by_model[r.model]
            entry["cost"] += r.cost
            entry["calls"] += 1
            entry["input_tokens"] += r.input_tokens
            entry["output_tokens"] += r.output_tokens

        savings = []
        for model, data in by_model.items():
            alt = get_cheaper_alternative(model)
            if alt is not None:
                alt_model, ratio = alt
                saved = data["cost"] * ratio
                if saved > 0.001:
                    savings.append({
                        "from": model,
                        "to": alt_model,
                        "savings_usd": round(saved, 4),
                        "savings_pct": round(ratio * 100),
                        "calls_affected": data["calls"],
                    })

        return {
            "session_id": self.session_id,
            "total_cost": round(total_cost, 4),
            "total_input_tokens": total_input,
            "total_output_tokens": total_output,
            "total_tokens": total_input + total_output,
            "total_calls": len(self.records),
            "duration_seconds": round(time.time() - self._start, 1),
            "by_model": by_model,
            "savings": savings,
            "budget": self._budget,
        }

    def _check_budget(self) -> None:
        if self._budget is None or self._budget_warned:
            return
        total = sum(r.cost for r in self.records)
        if total >= self._budget:
            self._budget_warned = True
            import sys
            print(
                f"\n[spent] BUDGET ALERT: ${total:.4f} spent "
                f"(budget: ${self._budget:.2f})",
                file=sys.stderr,
            )

    def _on_exit(self) -> None:
        if self.records and not self.quiet:
            from .dashboard import print_summary
            print_summary(self.summary())
