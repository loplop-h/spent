# Launch Plan for spent

## Timing
- Best days: Tuesday-Thursday
- Best time: 8-10 AM Eastern (2-4 PM Spain)
- Post all 3 simultaneously

---

## 1. HACKER NEWS (Show HN)

**Title:**
```
Show HN: Spent -- see what your LLM API calls actually cost (zero code changes)
```

**Body:**
```
I've been building apps with LLM APIs for a while and I had no real idea what anything cost until the bill arrived. I'd look at the Anthropic or OpenAI dashboard at the end of the month, see a number, and think "that seems high" -- but I had no idea which calls in which scripts were responsible.

The breaking point was when I realized a batch evaluation script was using gpt-4o for tasks that gpt-4o-mini could handle identically. I was spending roughly 17x more per call on output tokens. Nobody told me. I had to go manually read pricing pages and do the math.

So I built spent. It's a CLI tool and Python library that tracks every OpenAI and Anthropic API call, records the token counts, computes the cost using up-to-date pricing, and prints a breakdown when your script finishes.

The simplest usage is just prefixing your command:

    pip install spent
    spent run python app.py

No code changes needed. When the script exits, you get a per-model cost breakdown, total tokens, and automatic savings recommendations like "switch gpt-4o to gpt-4o-mini on these 12 calls, save $2.10."

How it works: spent monkey-patches the OpenAI and Anthropic SDK methods (chat.completions.create and messages.create) at import time. It wraps the original function, lets the call go through normally, then extracts token usage from the response object and records it in a local SQLite database at ~/.spent/data.db. The original response is returned unchanged. No proxy, no network changes, no latency added to the API calls themselves.

There's also a programmatic API if you prefer:

    from spent import track
    from openai import OpenAI
    client = track(OpenAI())

Other features: budget alerts (--budget 5.00), live terminal dashboard, session history, JSON/CSV export. All data stays local.

Limitations I want to be upfront about:

- Python only. No JS/TS SDK support yet.
- Only OpenAI and Anthropic SDKs are patched. Google AI, Mistral, etc. are on the roadmap but not wired up yet. (The pricing database has 40+ models from 6 providers, but the interception only works for the two SDKs.)
- Streaming responses -- token counts come from the final response usage field, which most SDK calls include, but some streaming configurations may not report it.
- It monkey-patches SDK internals, so it could break if openai or anthropic release a major SDK refactor. I pin to stable method paths and check for _spent_patched to avoid double-patching.

This is v0.1.0. MIT licensed.

GitHub: https://github.com/loplop-h/spent
PyPI: https://pypi.org/project/spent/

Happy to answer questions about the approach or take feature requests.
```

---

## 2. REDDIT (r/Python, r/MachineLearning, r/LocalLLaMA)

**Title:**
```
I built a tool that shows exactly where your OpenAI/Anthropic money goes -- and it found I was overspending by 94% on some calls
```

**Body:**
```
A few weeks ago I sat down and actually calculated what my LLM API calls cost per-model. The results were not great.

I had a script that runs gpt-4o for a classification task -- basically deciding if text fits into one of 5 categories. Simple task. gpt-4o-mini handles it with the same accuracy. But gpt-4o output tokens cost $10 per million, gpt-4o-mini costs $0.60. That's a 94% difference, and I had no way to see it without manually counting tokens and checking pricing tables.

The OpenAI dashboard shows you total spend per day, but not per-script, not per-model within a script, and definitely not "hey, you could use a cheaper model here." Anthropic's is similar.

So I built **spent**. It's a CLI wrapper and Python library that intercepts all OpenAI and Anthropic SDK calls, records token usage, computes cost, and gives you a breakdown when your script finishes.

Usage is one line in the terminal:

    pip install spent
    spent run python your_script.py

No code changes to your app. When it finishes you get a table showing each model, how many calls it made, the token count, the cost, and what percentage of your total it represents. It also suggests cheaper alternatives automatically.

Under the hood it monkey-patches the SDK create methods, extracts the usage field from responses, and stores everything in a SQLite database on your machine (~/.spent/data.db). Nothing leaves your computer.

It also has:
- Budget alerts: `spent run --budget 5.00 python train.py`
- A live dashboard: `spent dashboard`
- Historical reports: `spent report --today` or `spent report --json`
- CSV export for spreadsheet people

Current limitations: Python only, and only OpenAI + Anthropic SDKs are actually intercepted right now. The pricing database covers 40+ models across 6 providers (including Gemini, DeepSeek, Mistral, Groq), but active tracking is limited to the two patched SDKs. More providers are on the roadmap.

It's open source, MIT licensed, and has zero dependencies beyond click and rich.

If you're spending any nontrivial amount on LLM APIs, I'd genuinely recommend just running your main scripts under `spent run` once to see where the money goes. The results surprised me.

Source: https://github.com/loplop-h/spent
PyPI: https://pypi.org/project/spent/
```

---

## 3. TWITTER/X (Thread - 6 tweets)

**Tweet 1:**
```
I was mass spending on LLM APIs and had no idea which calls cost what.

OpenAI's dashboard shows a daily total. Anthropic's is similar. Neither tells you which script, which model, or which calls are burning your budget.

So I built something to find out.
```

**Tweet 2:**
```
First thing I discovered: a classification script was using gpt-4o when gpt-4o-mini would produce the same results.

Output token cost difference: $10.00 vs $0.60 per million tokens.

I was paying 94% more than necessary and had zero visibility into it.
```

**Tweet 3:**
```
The fix is one line in your terminal:

pip install spent
spent run python app.py

That's it. No code changes. When your script finishes, you get a per-model cost breakdown with automatic savings recommendations.
```

**Tweet 4:**
```
Here's what the output looks like:

spent               session a1b2c3

Total Cost:    $4.2731
Tokens:        125,430 (98k in / 27k out)
API Calls:     47

Model             Calls  Cost     Share
gpt-4o            12     $3.8100  89%
gpt-4o-mini       31     $0.4200  10%
claude-sonnet      4     $0.0431   1%

Savings: gpt-4o -> gpt-4o-mini: save $2.10 (55%)
```

**Tweet 5:**
```
What it does:

- Tracks all OpenAI + Anthropic API costs automatically
- 40+ models with up-to-date pricing
- Budget alerts (--budget 5.00)
- Live terminal dashboard
- Session history with JSON/CSV export
- SQLite local storage, 100% private
- Zero dependencies beyond click + rich
```

**Tweet 6:**
```
It's open source and MIT licensed. v0.1.0 -- Python only for now.

GitHub: github.com/loplop-h/spent
PyPI: pypi.org/project/spent/

pip install spent

If you're spending any nontrivial amount on LLM APIs, run your scripts under "spent run" once. The results might surprise you.
```

---

## Checklist de Lanzamiento

- [ ] Elegir dia (martes-jueves)
- [ ] Post en Hacker News a las 8-10 AM Eastern
- [ ] Post en r/Python inmediatamente despues
- [ ] Thread en Twitter/X inmediatamente despues
- [ ] Responder TODOS los comentarios las primeras 12 horas
- [ ] Post en r/MachineLearning al dia siguiente (no spam same-day)
- [ ] Submit a awesome-python, awesome-llm (semana siguiente)
