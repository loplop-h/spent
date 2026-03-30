<p align="center">
  <h1 align="center">spent</h1>
  <p align="center"><strong>See what your AI really costs. Zero code changes.</strong></p>
</p>

<p align="center">
  <a href="https://pypi.org/project/spent/"><img src="https://img.shields.io/pypi/v/spent?style=flat-square" alt="PyPI"></a>
  <a href="https://pypi.org/project/spent/"><img src="https://img.shields.io/pypi/pyversions/spent?style=flat-square" alt="Python"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue?style=flat-square" alt="License"></a>
  <a href="https://github.com/loplop-h/spent/stargazers"><img src="https://img.shields.io/github/stars/maxhu/spent?style=flat-square" alt="Stars"></a>
</p>

---

You're spending hundreds on LLM APIs every month. Do you know which calls cost what?

**spent** tracks every token, every model, every dollar -- automatically. One command. No code changes. Beautiful reports.

```
$ spent run python app.py

 ┌──────────────────────────────────────────┐
 │  spent                    session a1b2c3 │
 │                                          │
 │  Total Cost:    $4.2731                  │
 │  Tokens:        125,430  (98k in / 27k out)
 │  API Calls:     47                       │
 │  Duration:      2m 34s                   │
 └──────────────────────────────────────────┘

  Model                   Calls  Tokens     Cost     Share
  gpt-4o                  12     84,200     $3.8100  ████████░░ 89%
  gpt-4o-mini             31     38,100     $0.4200  █░░░░░░░░░ 10%
  claude-sonnet-4-6        4      3,130     $0.0431  ░░░░░░░░░░  1%

  Savings Opportunities: ~$2.1000
    gpt-4o -> gpt-4o-mini: save $2.10 (55%) on 12 calls
```

## Quick Start

```bash
pip install spent
```

### Option 1: Zero code changes (recommended)

Just prefix your command:

```bash
spent run python app.py
spent run python -m pytest
spent run --budget 5.00 python train.py
```

### Option 2: One line of code

```python
from spent import track
from openai import OpenAI

client = track(OpenAI())

# Use normally -- costs tracked automatically
response = client.chat.completions.create(
    model="gpt-4o",
    messages=[{"role": "user", "content": "Hello!"}],
)
# Exit summary printed automatically
```

Works with Anthropic too:

```python
from spent import track
from anthropic import Anthropic

client = track(Anthropic())
```

## Features

| Feature | Status |
|---------|--------|
| OpenAI cost tracking | Done |
| Anthropic cost tracking | Done |
| Beautiful terminal dashboard | Done |
| Per-model cost breakdown | Done |
| Savings recommendations | Done |
| Budget alerts | Done |
| Session history | Done |
| JSON/CSV export | Done |
| Google AI tracking | Roadmap |
| Auto model routing | Roadmap |
| Team cost sharing | Roadmap |
| CI/CD cost reports | Roadmap |

## Commands

```bash
# Track costs (zero code changes)
spent run python app.py

# Set a budget alert
spent run --budget 10.00 python app.py

# Live dashboard (watches costs in real-time)
spent dashboard

# View cost reports
spent report              # Recent sessions
spent report --today      # Today's costs
spent report --json       # Machine-readable
spent report --csv        # Spreadsheet-ready

# Clear all data
spent reset
```

## How It Works

**spent** transparently patches the OpenAI and Anthropic Python SDKs at import time. When your code calls `client.chat.completions.create(...)`, spent:

1. Intercepts the call (before and after)
2. Extracts token usage from the response
3. Calculates cost using up-to-date pricing
4. Stores the record in a local SQLite database
5. Returns the original response unchanged

Your code runs exactly the same. No API proxies. No network changes. No latency added to API calls themselves.

Data stays on your machine at `~/.spent/data.db`.

## Supported Models

40+ models with up-to-date pricing:

| Provider | Models |
|----------|--------|
| **OpenAI** | GPT-4o, GPT-4o-mini, GPT-4-Turbo, GPT-4, GPT-3.5-Turbo, o1, o3, o3-mini, o4-mini |
| **Anthropic** | Claude Opus 4, Claude Sonnet 4, Claude Haiku 4, Claude 3.5/3 family |
| **Google** | Gemini 2.5 Pro/Flash, 2.0 Flash, 1.5 Pro/Flash |
| **DeepSeek** | DeepSeek Chat, DeepSeek Reasoner |
| **Mistral** | Mistral Large, Mistral Small, Codestral |
| **Groq** | Llama 3.3 70B, Llama 3.1 8B, Mixtral 8x7B |

Unknown models are tracked with $0 cost (tokens still recorded).

## Budget Alerts

Set a budget and get warned when you exceed it:

```bash
# CLI
spent run --budget 5.00 python app.py

# Python
from spent import track, configure
configure(budget=5.00)
client = track(OpenAI())
```

When the budget is exceeded:
```
[spent] BUDGET ALERT: $5.0231 spent (budget: $5.00)
```

## Why spent?

| | spent | Manual tracking | LLM framework built-in |
|---|---|---|---|
| Code changes needed | 0 | Lots | Framework-specific |
| Works across providers | Yes | Manual per-provider | Usually one provider |
| Historical data | SQLite | Spreadsheets | In-memory only |
| Savings recommendations | Automatic | You do the math | No |
| Export formats | JSON, CSV | Copy-paste | Varies |
| Privacy | 100% local | Depends | Often cloud |

## Roadmap

- [ ] **Google AI / Vertex tracking** -- Gemini model support
- [ ] **Auto model routing** -- automatically use cheaper models for simple tasks
- [ ] **Team dashboards** -- aggregate costs across team members
- [ ] **CI/CD integration** -- cost reports in GitHub Actions / PR comments
- [ ] **Ollama / local model tracking** -- track local inference costs (compute time)
- [ ] **Web dashboard** -- browser-based cost explorer
- [ ] **Slack / Discord alerts** -- budget notifications in team channels
- [ ] **Cost anomaly detection** -- alert on unusual spending patterns

## Contributing

Contributions welcome! See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

```bash
git clone https://github.com/loplop-h/spent.git
cd spent
pip install -e ".[dev]"
pytest
```

## License

MIT
