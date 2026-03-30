# Examples

## Quick Start

```bash
# 1. Install
pip install spent

# 2. Setup hooks (once)
spent cc setup

# 3. Restart Claude Code, then open a side terminal:
spent cc live
```

## Commands

```bash
# Live terminal dashboard (keep in side pane)
spent cc live

# Quick status check
spent cc status

# Efficiency score only
spent cc score

# Session history (last 7 days)
spent cc history

# Efficiency tips
spent cc tips

# Toggle tracking on/off
spent cc on
spent cc off

# Web dashboard (alternative to TUI)
spent cc dashboard

# Claude Code skill (inside Claude Code)
/spent
```

## What gets tracked

Every Claude Code tool use is logged via hooks:
- **Productive** (green): Edit, Write, Agent -- creating code
- **Neutral** (gray): Read, Grep, Glob -- gathering info
- **Wasted** (red): Failed Bash, repeated Reads -- inefficiency

Your efficiency score = productive cost / total cost.
