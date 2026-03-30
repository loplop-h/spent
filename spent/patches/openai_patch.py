"""Transparent patch for the OpenAI Python SDK."""

from __future__ import annotations

import time
from functools import wraps


def patch() -> None:
    """Monkey-patch openai.resources.chat.completions.Completions.create
    and its async counterpart to track usage."""
    try:
        import openai.resources.chat.completions as mod
    except ImportError:
        return

    _patch_sync(mod)
    _patch_async(mod)

    # Also patch responses / completions if available
    try:
        import openai.resources.completions as legacy_mod
        _patch_sync_legacy(legacy_mod)
    except (ImportError, AttributeError):
        pass


def _patch_sync(mod) -> None:
    original = mod.Completions.create

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
    mod.Completions.create = tracked_create


def _patch_async(mod) -> None:
    original = mod.AsyncCompletions.create

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
    mod.AsyncCompletions.create = tracked_create


def _patch_sync_legacy(mod) -> None:
    original = mod.Completions.create

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
    mod.Completions.create = tracked_create


def _record_usage(response, model: str, elapsed_ms: int) -> None:
    """Extract token usage from an OpenAI response and record it."""
    usage = getattr(response, "usage", None)
    if usage is None:
        return

    from ..tracker import Tracker

    input_tokens = getattr(usage, "prompt_tokens", 0) or 0
    output_tokens = getattr(usage, "completion_tokens", 0) or 0
    actual_model = getattr(response, "model", model) or model

    Tracker.get().record(
        provider="openai",
        model=actual_model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        duration_ms=elapsed_ms,
    )
