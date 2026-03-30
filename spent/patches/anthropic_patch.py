"""Transparent patch for the Anthropic Python SDK."""

from __future__ import annotations

import time
from functools import wraps


def patch() -> None:
    """Monkey-patch anthropic.resources.messages.Messages.create
    and its async counterpart to track usage."""
    try:
        import anthropic.resources.messages as mod
    except ImportError:
        return

    _patch_sync(mod)
    _patch_async(mod)


def _patch_sync(mod) -> None:
    original = mod.Messages.create

    if getattr(original, "_spent_patched", False):
        return

    @wraps(original)
    def tracked_create(self, *args, **kwargs):
        start = time.perf_counter()
        response = original(self, *args, **kwargs)
        elapsed_ms = int((time.perf_counter() - start) * 1000)
        _record_usage(response, kwargs.get("model", "unknown"), elapsed_ms)
        return response

    tracked_create._spent_patched = True
    mod.Messages.create = tracked_create


def _patch_async(mod) -> None:
    original = mod.AsyncMessages.create

    if getattr(original, "_spent_patched", False):
        return

    @wraps(original)
    async def tracked_create(self, *args, **kwargs):
        start = time.perf_counter()
        response = await original(self, *args, **kwargs)
        elapsed_ms = int((time.perf_counter() - start) * 1000)
        _record_usage(response, kwargs.get("model", "unknown"), elapsed_ms)
        return response

    tracked_create._spent_patched = True
    mod.AsyncMessages.create = tracked_create


def _record_usage(response, model: str, elapsed_ms: int) -> None:
    """Extract token usage from an Anthropic response and record it."""
    usage = getattr(response, "usage", None)
    if usage is None:
        return

    from ..tracker import Tracker

    input_tokens = getattr(usage, "input_tokens", 0) or 0
    output_tokens = getattr(usage, "output_tokens", 0) or 0
    actual_model = getattr(response, "model", model) or model

    Tracker.get().record(
        provider="anthropic",
        model=actual_model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        duration_ms=elapsed_ms,
    )
