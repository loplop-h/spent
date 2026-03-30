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


def track(client, *, budget: float | None = None):
    """Wrap an LLM client to track all API costs.

    Supports OpenAI and Anthropic clients. Returns the same client
    with transparent cost tracking enabled.

    Args:
        client: An OpenAI() or Anthropic() client instance.
        budget: Optional budget alert threshold in USD.

    Returns:
        The same client, now tracked.

    Example:
        from openai import OpenAI
        from spent import track

        client = track(OpenAI())
        # Use client normally -- costs are tracked automatically.
    """
    from .tracker import Tracker
    from .patches import apply_all

    tracker = Tracker.get()
    if budget is not None:
        tracker.set_budget(budget)

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
