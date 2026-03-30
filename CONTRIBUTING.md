# Contributing to spent

Thanks for your interest in contributing!

## Setup

```bash
git clone https://github.com/loplop-h/spent.git
cd spent
pip install -e ".[dev]"
```

## Running Tests

```bash
pytest
```

## Code Style

We use [ruff](https://github.com/astral-sh/ruff) for linting:

```bash
ruff check .
ruff format .
```

## Adding a New Provider

1. Create a new patch file in `spent/patches/` (see `openai_patch.py` for reference)
2. Add the provider's model pricing to `spent/pricing.py`
3. Import and call the patch in `spent/patches/__init__.py`
4. Add tests

## Pull Requests

- Keep PRs focused on a single change
- Include tests for new functionality
- Update README if adding user-facing features
