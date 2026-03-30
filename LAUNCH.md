# Launch Plan for spent (Claude Code Session Cost Tracker)

## Timing
- Best days: Tuesday-Thursday
- Best time: 8-10 AM Eastern (2-4 PM Spain)
- Post all 3 simultaneously

---

## 1. HACKER NEWS (Show HN)

**Title:**
```
Show HN: Spent -- see your Claude Code efficiency score and session costs
```

**Body:**
```
I use Claude Code every day and I had no idea how much each session actually cost or where the money went. The Anthropic dashboard gives you a monthly total, but it doesn't tell you which sessions were productive and which were burning tokens on repeated file reads and failed bash commands.

The breaking point was when I watched a session spend 40+ tool calls going in circles -- re-reading the same files, running broken commands, grepping for things it had already found. The session cost $8 and produced two small edits. I thought: what if I could score this?

So I built spent. It's a CLI tool that hooks into Claude Code sessions (via PostToolUse, SessionStart, and Stop hooks), classifies every action, and computes an efficiency score from 0-100%.

The classification is simple:
- Productive: Edit, Write, Agent calls -- actions that change code
- Neutral: Read, Grep, Glob -- necessary reconnaissance
- Wasted: failed Bash commands, repeated identical Reads, tool errors

Setup is two commands:

    pip install spent
    spent cc setup

That configures the Claude Code hooks. From then on, every session is tracked automatically.

The efficiency score is the interesting part. It's the ratio of productive actions to total actions, weighted by estimated cost. A session that makes 10 edits after 5 reads scores higher than one that reads 30 files and makes 2 edits.

You can see it live while working:

    spent cc live

That opens a terminal TUI you can put in a side pane -- it updates in real-time as Claude Code runs, showing cost accumulation, action classification, and the running efficiency score.

There's also a web dashboard with a shareable card if you want to compare scores or flex your 94% session.

How it works under the hood: the hooks fire on every tool use and session event, sending the action type and metadata to a local SQLite database. No external API calls. Nothing leaves your machine. The cost estimates are based on the model and token counts from the hook payloads.

Limitations I want to be upfront about:

- Costs are estimates, not exact billing amounts. Anthropic doesn't expose per-session billing through hooks, so spent uses token counts and published pricing to approximate. It's directionally accurate but won't match your invoice to the cent.
- Requires hooks setup. spent cc setup writes to your Claude Code settings, which means you need to be comfortable with that.
- The efficiency classification is opinionated. Someone doing deep code archaeology might have many Reads that are genuinely productive. The defaults work for typical coding sessions, but they're not universally correct.
- Python only for the CLI. The hooks themselves are language-agnostic since Claude Code runs them as shell commands.

It's open source and MIT licensed.

GitHub: https://github.com/loplop-h/spent

Happy to answer questions about the hook architecture or the scoring algorithm.
```

---

## 2. REDDIT (r/ClaudeAI)

**Title:**
```
I built a tool that classifies every Claude Code action as productive or wasted -- my efficiency score was 61%
```

**Body:**
```
I've been using Claude Code daily for months and I always wondered: how much does each session actually cost, and am I using it well?

The Anthropic dashboard shows a monthly number. That's it. No breakdown by session, no insight into whether Claude spent its time editing code or spinning its wheels re-reading the same file 15 times.

So I built **spent** -- a CLI tool that hooks into Claude Code and tracks every single action. It classifies each one:

- **Productive**: Edit, Write, Agent -- actions that produce code changes
- **Neutral**: Read, Grep, Glob -- necessary research
- **Wasted**: failed Bash commands, repeated identical Reads, tool errors

Then it computes an **efficiency score from 0-100%**.

My first session scored 61%. That stung. I watched the breakdown and saw that Claude had re-read the same 3 files six times each and ran 4 bash commands that all failed with the same error. Nearly 40% of the session cost was reconnaissance that went nowhere.

After adjusting my prompts to be more specific and front-loading context, I got subsequent sessions up to 85-90%.

**The setup is two commands:**

```
pip install spent
spent cc setup
```

That installs hooks into Claude Code (PostToolUse, SessionStart, Stop). From then on, tracking is automatic.

**What you get:**

- `spent cc live` -- a terminal TUI for a side pane, updates in real-time as Claude works
- Web dashboard with a shareable efficiency card
- `/spent` skill you can use inside Claude Code itself
- Per-session cost estimates based on model and token counts
- All local, SQLite storage, zero API calls

**Important caveat:** costs are estimates. Anthropic doesn't expose exact per-session billing through hooks, so spent uses token counts and published pricing to approximate. It's close but not invoice-accurate.

The efficiency score is opinionated -- Reads aren't inherently wasted, but repeated identical Reads are. Failed commands aren't inherently wasted, but failing the same command 4 times is. The scoring tries to capture "did this session spend its tokens on things that produced results?"

I'm curious what scores other people get. I suspect heavy refactoring sessions score lower (lots of reading) and greenfield sessions score higher (lots of writing).

**GitHub:** https://github.com/loplop-h/spent

Open source, MIT licensed. Would love feedback on the classification logic -- it's the most subjective part of the tool.
```

---

## 3. TWITTER/X (Single Tweet)

```
I built a tool that scores your Claude Code sessions on efficiency (productive edits vs wasted reads and failed commands). My first score: 61%. Now I'm at 90%.

pip install spent && spent cc setup

github.com/loplop-h/spent
```

---

## Launch Checklist

- [ ] Pick a day (Tuesday-Thursday)
- [ ] Post on Hacker News at 8-10 AM Eastern
- [ ] Post on r/ClaudeAI immediately after
- [ ] Tweet immediately after
- [ ] Reply to ALL comments in the first 12 hours
- [ ] Cross-post to r/Python the next day (different angle: the hooks architecture)
- [ ] Submit to awesome-claude, awesome-python (the following week)
