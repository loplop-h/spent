"""Transparent patch for the OpenAI Python SDK."""

from __future__ import annotations

import time
from functools import wraps
from typing import Generator, AsyncGenerator

# Rough estimate: 1 token ~ 4 characters for English text.
_CHARS_PER_TOKEN = 4


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
        is_stream = kwargs.get("stream", False)
        kwargs = _maybe_reroute(kwargs)
        start = time.perf_counter()
        response = original(self, *args, **kwargs)

        if is_stream:
            return _wrap_stream_sync(
                response,
                model=kwargs.get("model", "unknown"),
                start=start,
            )

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
        is_stream = kwargs.get("stream", False)
        kwargs = _maybe_reroute(kwargs)
        start = time.perf_counter()
        response = await original(self, *args, **kwargs)

        if is_stream:
            return _wrap_stream_async(
                response,
                model=kwargs.get("model", "unknown"),
                start=start,
            )

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


# ---------------------------------------------------------------------------
# Streaming wrappers
# ---------------------------------------------------------------------------

def _wrap_stream_sync(
    stream,
    model: str,
    start: float,
) -> Generator:
    """Wrap a sync streaming response to accumulate chunks and record usage."""
    collected_content: list[str] = []
    final_usage = None
    actual_model = model

    for chunk in stream:
        # Track the model from the first chunk that has it
        chunk_model = getattr(chunk, "model", None)
        if chunk_model:
            actual_model = chunk_model

        # Accumulate content text from delta
        _accumulate_chunk_content(chunk, collected_content)

        # Check for usage in each chunk (OpenAI sends it in the last chunk
        # when stream_options={"include_usage": True})
        chunk_usage = getattr(chunk, "usage", None)
        if chunk_usage is not None:
            final_usage = chunk_usage

        yield chunk

    # Stream complete -- record usage
    elapsed_ms = int((time.perf_counter() - start) * 1000)
    _record_stream_usage(
        final_usage=final_usage,
        collected_content=collected_content,
        model=actual_model,
        elapsed_ms=elapsed_ms,
    )


async def _wrap_stream_async(
    stream,
    model: str,
    start: float,
) -> AsyncGenerator:
    """Wrap an async streaming response to accumulate chunks and record usage."""
    collected_content: list[str] = []
    final_usage = None
    actual_model = model

    async for chunk in stream:
        chunk_model = getattr(chunk, "model", None)
        if chunk_model:
            actual_model = chunk_model

        _accumulate_chunk_content(chunk, collected_content)

        chunk_usage = getattr(chunk, "usage", None)
        if chunk_usage is not None:
            final_usage = chunk_usage

        yield chunk

    elapsed_ms = int((time.perf_counter() - start) * 1000)
    _record_stream_usage(
        final_usage=final_usage,
        collected_content=collected_content,
        model=actual_model,
        elapsed_ms=elapsed_ms,
    )


def _accumulate_chunk_content(chunk, collected_content: list[str]) -> None:
    """Extract text content from a streaming chunk's delta and append it."""
    choices = getattr(chunk, "choices", None)
    if not choices:
        return
    for choice in choices:
        delta = getattr(choice, "delta", None)
        if delta is None:
            continue
        content = getattr(delta, "content", None)
        if content:
            collected_content.append(content)


def _record_stream_usage(
    final_usage,
    collected_content: list[str],
    model: str,
    elapsed_ms: int,
) -> None:
    """Record usage from a completed stream.

    If the final chunk contained a usage object (stream_options include_usage),
    use that. Otherwise, estimate output tokens from the accumulated content.
    """
    from ..tracker import Tracker

    if final_usage is not None:
        input_tokens = getattr(final_usage, "prompt_tokens", 0) or 0
        output_tokens = getattr(final_usage, "completion_tokens", 0) or 0
    else:
        # Estimate tokens from accumulated content
        full_text = "".join(collected_content)
        input_tokens = 0  # Cannot know input tokens from stream alone
        output_tokens = max(1, len(full_text) // _CHARS_PER_TOKEN)

    Tracker.get().record(
        provider="openai",
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        duration_ms=elapsed_ms,
    )


# ---------------------------------------------------------------------------
# Routing and non-stream recording
# ---------------------------------------------------------------------------

def _maybe_reroute(kwargs: dict) -> dict:
    """If router is enabled, reroute to optimal model."""
    try:
        from ..router import Router
        router = Router.get()
        if not router.enabled:
            return kwargs
        messages = kwargs.get("messages")
        model = kwargs.get("model", "unknown")
        if messages and model:
            new_model = router.route(messages, model)
            if new_model != model:
                kwargs = {**kwargs, "model": new_model}
    except Exception:
        pass
    return kwargs


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
