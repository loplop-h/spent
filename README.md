<p align="center">
  <h1 align="center">spent</h1>
  <p align="center"><strong>See what your Claude Code sessions really cost.</strong></p>
  <p align="center">Efficiency score. Productive vs wasted breakdown. Live terminal dashboard.</p>
</p>

<p align="center">
  <a href="https://pypi.org/project/spent/"><img src="https://img.shields.io/pypi/v/spent?style=flat-square" alt="PyPI"></a>
  <a href="https://pypi.org/project/spent/"><img src="https://img.shields.io/pypi/pyversions/spent?style=flat-square" alt="Python"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue?style=flat-square" alt="License"></a>
  <a href="https://github.com/loplop-h/spent/stargazers"><img src="https://img.shields.io/github/stars/loplop-h/spent?style=flat-square" alt="Stars"></a>
</p>

---

You use Claude Code every day. Do you know how much each session costs? Which tool uses are productive and which are wasted?

**spent** tracks every tool use, classifies it as productive, neutral, or wasted, and gives you an efficiency score. No API keys. No external services. Everything runs locally from Claude Code's own hook system.

<p align="center">
  <img src="https://raw.githubusercontent.com/loplop-h/spent/master/docs/tui-screenshot.png" alt="spent TUI dashboard" width="600">
</p>

<details>
<summary><strong>Web dashboard</strong></summary>
<p align="center">
  <img src="https://raw.githubusercontent.com/loplop-h/spent/master/docs/web-dashboard.png" alt="spent web dashboard" width="700">
</p>
</details>

## Quick Start

```bash
pip install spent
spent cc setup    # install Claude Code hooks (once)
spent cc live     # open dashboard in a side terminal
```

That's it. `spent cc setup` installs three hooks into `~/.claude/settings.json`:

- **PostToolUse** -- logs every tool invocation (Edit, Read, Bash, Grep, etc.)
- **SessionStart** -- marks when a session begins
- **Stop** -- marks session end and writes the final summary

Restart Claude Code after setup. Costs are tracked automatically from that point.

## Features

| Feature | Status |
|---------|--------|
| Per-session cost tracking | Done |
| Efficiency score (0-100) | Done |
| Productive / neutral / wasted classification | Done |
| Live terminal dashboard (`spent cc live`) | Done |
| Per-tool cost breakdown | Done |
| Session history and trends | Done |
| Web dashboard (`spent cc dashboard`) | Done |
| Efficiency tips | Done |
| Claude Code skill (`/spent`) | Done |
| Statusline integration | Done |
| JSON export | Done |
| Multi-model pricing (Opus, Sonnet, Haiku) | Done |
| Cost anomaly detection | Roadmap |
| Team cost aggregation | Roadmap |
| CI usage reports | Roadmap |

## How It Works

Claude Code hooks fire on every tool use. spent logs each event to a local JSONL file at `~/.spent/claude-sessions.jsonl` with:

- Timestamp
- Tool name (Edit, Read, Bash, Grep, Glob, Agent, etc.)
- Input/output character counts
- Session ID
- Model identifier

From this log, spent estimates token counts (characters / 4, plus context overhead that grows with conversation length) and calculates cost using Claude model pricing:

| Model | Input (per 1M tokens) | Output (per 1M tokens) |
|-------|----------------------|------------------------|
| Opus | $15.00 | $75.00 |
| Sonnet | $3.00 | $15.00 |
| Haiku | $0.80 | $4.00 |

No API calls. No network requests. Everything is estimated locally from hook data.

## Commands

```bash
# Setup (run once)
spent cc setup          # install hooks + statusline

# Live monitoring
spent cc live           # full-screen terminal dashboard (side pane)
spent cc status         # quick panel with score + cost + breakdown
spent cc score          # one-line efficiency score

# Session history
spent cc history        # last 7 days of sessions
spent cc history -d 30  # last 30 days
spent cc tips           # efficiency tips for current session

# Web dashboard
spent cc dashboard      # open browser dashboard (localhost:5050)

# Controls
spent cc on             # enable tracking
spent cc off            # disable tracking

# Data
spent session           # current session detail
spent session --today   # all sessions from today
spent session --json    # machine-readable output
spent reset             # delete all tracked data
```

## Efficiency Scoring

Every tool use is classified into one of three categories:

### Productive

Actions that produce code or move work forward.

- **Edit** / **Write** / **MultiEdit** -- code written or modified
- **Agent** -- task delegation
- **Bash** -- commands that succeed (no error indicators)

### Neutral

Information gathering. Necessary but not directly productive.

- **Read** / **Grep** / **Glob** -- searching and reading files
- **TodoRead** / **TodoWrite** -- task management
- **WebSearch** / **WebFetch** -- research

### Wasted

Actions that cost tokens but didn't advance the task.

- **Bash** with error output -- failed commands, stack traces
- **Read** of the same file within 60 seconds -- redundant reads
- **Edit** of the same file within 30 seconds of another Edit -- rapid re-edits (usually fixing a mistake)

The efficiency score is a weighted formula:

```
score = ((productive * 1.0) + (neutral * 0.5) + (wasted * 0.0)) / total * 100
```

A score of 70+ is good. Below 40 means a lot of time is going to failed attempts and re-work.

## Claude Code Skill

spent includes a `/spent` skill for use directly inside Claude Code sessions:

```
/spent              # show current session costs and efficiency
```

The skill is automatically available if spent is installed. It reads the same JSONL log and displays a formatted summary without leaving your Claude Code session.

## Privacy

- All data stays on your machine at `~/.spent/`
- No external API calls, no telemetry, no network requests
- Hook scripts run locally as async shell commands
- The JSONL log contains only tool names, character counts, and timestamps -- no file contents, no prompts, no code

## Roadmap

- [ ] **Cost anomaly detection** -- alert when a session is burning tokens faster than usual
- [ ] **Team dashboards** -- aggregate costs across team members
- [ ] **CI usage reports** -- cost per PR, cost per branch
- [ ] **Session comparison** -- compare efficiency across sessions
- [ ] **Custom classification rules** -- let users define their own productive/wasted rules
- [ ] **Notification thresholds** -- alert when session cost exceeds a limit

## Contributing

Contributions welcome. See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

```bash
git clone https://github.com/loplop-h/spent.git
cd spent
pip install -e ".[dev]"
pytest
```

## License

MIT
