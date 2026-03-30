"""SDK patches -- intercept LLM API calls transparently."""

from __future__ import annotations

_patched = False


def apply_all() -> None:
    """Apply all available SDK patches. Safe to call multiple times."""
    global _patched
    if _patched:
        return
    _patched = True

    from .openai_patch import patch as patch_openai
    from .anthropic_patch import patch as patch_anthropic

    patch_openai()
    patch_anthropic()
