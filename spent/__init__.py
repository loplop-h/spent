"""spent -- see what your AI really costs.

Usage (zero code changes):
    $ spent run python app.py

Usage (programmatic):
    from spent import track
    from openai import OpenAI

    client = track(OpenAI())
"""

from __future__ import annotations

__version__ = "0.1.0"


def track(client, *, budget: float | None = None, optimize: bool = False):
    """Wrap an LLM client to track all API costs.

    Supports OpenAI and Anthropic clients. Returns the same client
    with transparent cost tracking enabled.

    Args:
        client: An OpenAI() or Anthropic() client instance.
        budget: Optional budget alert threshold in USD.
        optimize: Enable smart model routing. Simple tasks are
            automatically routed to cheaper models.

    Returns:
        The same client, now tracked (and optionally optimized).

    Example:
        from openai import OpenAI
        from spent import track

        # Track only:
        client = track(OpenAI())

        # Track + auto-optimize:
        client = track(OpenAI(), optimize=True)
        # Classification tasks -> gpt-4o-mini (auto)
        # Complex reasoning -> stays on gpt-4o
    """
    from .tracker import Tracker
    from .patches import apply_all
    from .router import Router

    tracker = Tracker.get()
    if budget is not None:
        tracker.set_budget(budget)

    router = Router.get()
    router.enabled = optimize

    apply_all()
    return client


def configure(*, budget: float | None = None, quiet: bool = False) -> None:
    """Configure the global tracker.

    Args:
        budget: Budget alert threshold in USD.
        quiet: Suppress the exit summary.
    """
    from .tracker import Tracker
    tracker = Tracker.get()
    if budget is not None:
        tracker.set_budget(budget)
    tracker.quiet = quiet


def summary() -> dict:
    """Get the current session cost summary as a dict."""
    from .tracker import Tracker
    return Tracker.get().summary()
