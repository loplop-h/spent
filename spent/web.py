"""Web dashboard for spent -- beautiful real-time cost visualization.

Serves a single-page dashboard on http://localhost:5050 using only
Python's built-in http.server. No Flask, no FastAPI, no dependencies
beyond the standard library and spent itself.

Usage:
    spent web              # start on default port 5050
    spent web --port 8080  # custom port
    spent web --no-open    # don't auto-open browser
"""

from __future__ import annotations

import json
import threading
import webbrowser
from datetime import datetime, timedelta, timezone
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Any

from .pricing import get_cheaper_alternative, calculate_cost, PRICING
from .storage import Storage

DEFAULT_PORT = 5050


# ---------------------------------------------------------------------------
# Data helpers
# ---------------------------------------------------------------------------

def _safe_json(obj: Any) -> str:
    return json.dumps(obj, default=str, ensure_ascii=False)


def _build_stats(storage: Storage) -> dict:
    """Aggregate statistics for the /api/stats endpoint."""
    today = storage.get_today()

    total_cost = sum(r["cost"] for r in today)
    total_calls = len(today)
    total_input = sum(r["input_tokens"] for r in today)
    total_output = sum(r["output_tokens"] for r in today)
    total_tokens = total_input + total_output

    # Burn rate: cost per hour based on today's data
    burn_rate = 0.0
    if today:
        first_ts = today[0]["timestamp"]
        last_ts = today[-1]["timestamp"]
        try:
            t0 = datetime.fromisoformat(first_ts)
            t1 = datetime.fromisoformat(last_ts)
            span_hours = max((t1 - t0).total_seconds() / 3600, 0.01)
            burn_rate = total_cost / span_hours
        except (ValueError, TypeError):
            burn_rate = 0.0

    # Cost by model
    by_model: dict[str, dict[str, float | int]] = {}
    for r in today:
        m = r["model"]
        if m not in by_model:
            by_model[m] = {"cost": 0.0, "calls": 0, "input_tokens": 0, "output_tokens": 0}
        by_model[m]["cost"] += r["cost"]
        by_model[m]["calls"] += 1
        by_model[m]["input_tokens"] += r["input_tokens"]
        by_model[m]["output_tokens"] += r["output_tokens"]

    # Cost over time (hourly buckets for today)
    hourly: dict[str, float] = {}
    for r in today:
        try:
            ts = datetime.fromisoformat(r["timestamp"])
            bucket = ts.strftime("%Y-%m-%d %H:00")
        except (ValueError, TypeError):
            bucket = "unknown"
        hourly[bucket] = hourly.get(bucket, 0.0) + r["cost"]

    # Savings opportunities
    savings: list[dict] = []
    savings_by_model: dict[str, dict] = {}
    for r in today:
        model = r["model"]
        alt = get_cheaper_alternative(model)
        if alt is None:
            continue
        alt_model, savings_ratio = alt
        alt_cost = calculate_cost(alt_model, r["input_tokens"], r["output_tokens"])
        saved = r["cost"] - alt_cost
        if saved <= 0:
            continue
        if model not in savings_by_model:
            savings_by_model[model] = {
                "from_model": model,
                "to_model": alt_model,
                "calls_affected": 0,
                "current_cost": 0.0,
                "optimized_cost": 0.0,
                "savings": 0.0,
            }
        savings_by_model[model]["calls_affected"] += 1
        savings_by_model[model]["current_cost"] += r["cost"]
        savings_by_model[model]["optimized_cost"] += alt_cost
        savings_by_model[model]["savings"] += saved

    for entry in savings_by_model.values():
        entry["current_cost"] = round(entry["current_cost"], 6)
        entry["optimized_cost"] = round(entry["optimized_cost"], 6)
        entry["savings"] = round(entry["savings"], 6)
        savings.append(entry)

    total_possible_savings = sum(s["savings"] for s in savings)

    # Projections
    now = datetime.now(timezone.utc)
    hours_elapsed_today = now.hour + now.minute / 60 + now.second / 3600
    hours_elapsed_today = max(hours_elapsed_today, 0.01)

    projected_today = total_cost
    projected_week = burn_rate * 40 if burn_rate > 0 else total_cost * 7
    projected_month = burn_rate * 160 if burn_rate > 0 else total_cost * 30
    optimized_month = projected_month - (total_possible_savings * 30) if total_possible_savings > 0 else projected_month

    # All-time total
    all_time_cost = storage.get_total_cost()

    return {
        "total_cost": round(total_cost, 6),
        "all_time_cost": round(all_time_cost, 6),
        "total_calls": total_calls,
        "total_tokens": total_tokens,
        "total_input": total_input,
        "total_output": total_output,
        "burn_rate": round(burn_rate, 4),
        "by_model": by_model,
        "hourly": hourly,
        "savings": savings,
        "total_possible_savings": round(total_possible_savings, 6),
        "projections": {
            "today": round(projected_today, 4),
            "week": round(projected_week, 4),
            "month": round(projected_month, 4),
            "optimized_month": round(optimized_month, 4),
        },
    }


def _build_today(storage: Storage) -> list[dict]:
    """Today's records for /api/today."""
    records = storage.get_today()
    # Return last 50, most recent first
    return list(reversed(records[-50:]))


def _build_sessions(storage: Storage) -> list[dict]:
    """Session list for /api/sessions."""
    return storage.get_sessions(limit=20)


# ---------------------------------------------------------------------------
# HTML dashboard (single string, inline CSS/JS)
# ---------------------------------------------------------------------------

DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>spent -- AI Cost Dashboard</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.7/dist/chart.umd.min.js"></script>
<style>
/* -- Reset & base -- */
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

:root {
    --bg: #0d1117;
    --card: #161b22;
    --border: #30363d;
    --text: #e6edf3;
    --text-dim: #8b949e;
    --green: #3fb950;
    --yellow: #d29922;
    --red: #f85149;
    --blue: #58a6ff;
    --purple: #bc8cff;
    --light-blue: #79c0ff;
    --radius: 12px;
    --shadow: 0 2px 8px rgba(0,0,0,0.3);
}

body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif;
    background: var(--bg);
    color: var(--text);
    line-height: 1.5;
    min-height: 100vh;
}

a { color: var(--blue); text-decoration: none; }
a:hover { text-decoration: underline; }

/* -- Layout -- */
.container {
    max-width: 1400px;
    margin: 0 auto;
    padding: 24px 24px 48px;
}

header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 28px;
    padding-bottom: 16px;
    border-bottom: 1px solid var(--border);
}

header .logo {
    display: flex;
    align-items: center;
    gap: 12px;
}

header .logo h1 {
    font-size: 24px;
    font-weight: 700;
    letter-spacing: -0.5px;
}

header .logo .badge {
    font-size: 11px;
    font-weight: 600;
    background: var(--blue);
    color: var(--bg);
    padding: 2px 8px;
    border-radius: 6px;
    text-transform: uppercase;
    letter-spacing: 0.5px;
}

header .meta {
    display: flex;
    align-items: center;
    gap: 16px;
    font-size: 13px;
    color: var(--text-dim);
}

header .meta .dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background: var(--green);
    display: inline-block;
    animation: pulse 2s ease-in-out infinite;
}

@keyframes pulse {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.4; }
}

/* -- Stat cards -- */
.stat-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
    gap: 16px;
    margin-bottom: 24px;
}

.stat-card {
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 20px 24px;
    box-shadow: var(--shadow);
    transition: transform 0.15s ease, box-shadow 0.15s ease;
}

.stat-card:hover {
    transform: translateY(-2px);
    box-shadow: 0 4px 16px rgba(0,0,0,0.4);
}

.stat-card .label {
    font-size: 12px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.8px;
    color: var(--text-dim);
    margin-bottom: 6px;
}

.stat-card .value {
    font-size: 32px;
    font-weight: 700;
    letter-spacing: -1px;
    line-height: 1.2;
}

.stat-card .sub {
    font-size: 12px;
    color: var(--text-dim);
    margin-top: 4px;
}

.cost-green .value { color: var(--green); }
.cost-yellow .value { color: var(--yellow); }
.cost-red .value { color: var(--red); }

/* -- Charts row -- */
.chart-grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 16px;
    margin-bottom: 24px;
}

@media (max-width: 900px) {
    .chart-grid { grid-template-columns: 1fr; }
}

.chart-card {
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 20px 24px;
    box-shadow: var(--shadow);
}

.chart-card h3 {
    font-size: 14px;
    font-weight: 600;
    color: var(--text-dim);
    margin-bottom: 16px;
    text-transform: uppercase;
    letter-spacing: 0.5px;
}

.chart-wrap {
    position: relative;
    width: 100%;
    max-height: 300px;
}

/* -- Savings banner -- */
.savings-section {
    margin-bottom: 24px;
}

.savings-banner {
    background: linear-gradient(135deg, #1a2332 0%, #162218 100%);
    border: 1px solid #1f4529;
    border-radius: var(--radius);
    padding: 20px 24px;
    margin-bottom: 16px;
    display: flex;
    align-items: center;
    justify-content: space-between;
}

.savings-banner .amount {
    font-size: 28px;
    font-weight: 700;
    color: var(--green);
}

.savings-banner .label {
    font-size: 14px;
    color: var(--text-dim);
}

.savings-banner.no-savings {
    background: var(--card);
    border-color: var(--border);
}

.savings-banner.no-savings .amount {
    color: var(--text-dim);
    font-size: 18px;
}

/* -- Tables -- */
.table-card {
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 20px 24px;
    box-shadow: var(--shadow);
    margin-bottom: 24px;
    overflow-x: auto;
}

.table-card h3 {
    font-size: 14px;
    font-weight: 600;
    color: var(--text-dim);
    margin-bottom: 16px;
    text-transform: uppercase;
    letter-spacing: 0.5px;
}

table {
    width: 100%;
    border-collapse: collapse;
    font-size: 13px;
}

th {
    text-align: left;
    padding: 10px 12px;
    border-bottom: 2px solid var(--border);
    font-weight: 600;
    color: var(--text-dim);
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    cursor: pointer;
    user-select: none;
    white-space: nowrap;
}

th:hover { color: var(--blue); }

th.sort-asc::after { content: ' \25B2'; font-size: 9px; }
th.sort-desc::after { content: ' \25BC'; font-size: 9px; }

td {
    padding: 10px 12px;
    border-bottom: 1px solid var(--border);
    color: var(--text);
    white-space: nowrap;
}

tr:last-child td { border-bottom: none; }

tr:hover td { background: rgba(88, 166, 255, 0.04); }

td.cost { font-weight: 600; font-variant-numeric: tabular-nums; }
td.tokens { font-variant-numeric: tabular-nums; color: var(--text-dim); }
td.timestamp { color: var(--text-dim); font-size: 12px; }

.model-tag {
    display: inline-block;
    padding: 2px 8px;
    border-radius: 6px;
    font-size: 12px;
    font-weight: 500;
    background: rgba(88, 166, 255, 0.12);
    color: var(--blue);
    white-space: nowrap;
}

.model-tag.anthropic { background: rgba(188, 140, 255, 0.12); color: var(--purple); }
.model-tag.google { background: rgba(63, 185, 80, 0.12); color: var(--green); }
.model-tag.openai { background: rgba(88, 166, 255, 0.12); color: var(--blue); }

.arrow { color: var(--green); font-weight: 600; margin: 0 6px; }

.savings-amount { color: var(--green); font-weight: 700; }

/* -- Projections bar -- */
.projections-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
    gap: 16px;
    margin-bottom: 24px;
}

.proj-card {
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 16px 20px;
    text-align: center;
    box-shadow: var(--shadow);
}

.proj-card .proj-label {
    font-size: 11px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.8px;
    color: var(--text-dim);
    margin-bottom: 6px;
}

.proj-card .proj-value {
    font-size: 24px;
    font-weight: 700;
    color: var(--text);
    letter-spacing: -0.5px;
}

.proj-card.optimized .proj-value { color: var(--green); }
.proj-card.optimized { border-color: #1f4529; }

/* -- Empty state -- */
.empty-state {
    text-align: center;
    padding: 60px 20px;
    color: var(--text-dim);
}

.empty-state h2 {
    font-size: 20px;
    margin-bottom: 8px;
    color: var(--text);
}

.empty-state p { font-size: 14px; }

.empty-state code {
    background: var(--card);
    border: 1px solid var(--border);
    padding: 2px 8px;
    border-radius: 6px;
    font-size: 13px;
}

/* -- Footer -- */
footer {
    text-align: center;
    padding: 24px;
    font-size: 12px;
    color: var(--text-dim);
    border-top: 1px solid var(--border);
    margin-top: 16px;
}

/* -- Pagination -- */
.pagination {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 8px;
    margin-top: 16px;
}

.pagination button {
    background: var(--card);
    border: 1px solid var(--border);
    color: var(--text);
    padding: 6px 14px;
    border-radius: 6px;
    font-size: 12px;
    cursor: pointer;
    transition: background 0.15s;
}

.pagination button:hover:not(:disabled) {
    background: var(--border);
}

.pagination button:disabled {
    opacity: 0.4;
    cursor: not-allowed;
}

.pagination .page-info {
    font-size: 12px;
    color: var(--text-dim);
}

/* -- Loading shimmer -- */
.shimmer {
    background: linear-gradient(90deg, var(--card) 25%, #1c2333 50%, var(--card) 75%);
    background-size: 200% 100%;
    animation: shimmer 1.5s infinite;
    border-radius: 6px;
    height: 20px;
}

@keyframes shimmer {
    0% { background-position: 200% 0; }
    100% { background-position: -200% 0; }
}

/* -- Scrollbar -- */
::-webkit-scrollbar { width: 8px; height: 8px; }
::-webkit-scrollbar-track { background: var(--bg); }
::-webkit-scrollbar-thumb { background: var(--border); border-radius: 4px; }
::-webkit-scrollbar-thumb:hover { background: #484f58; }
</style>
</head>
<body>

<div class="container">
    <header>
        <div class="logo">
            <h1>spent</h1>
            <span class="badge">live</span>
        </div>
        <div class="meta">
            <span><span class="dot"></span> Auto-refresh 5s</span>
            <span id="last-update">--</span>
        </div>
    </header>

    <!-- Stat cards -->
    <div class="stat-grid" id="stat-grid">
        <div class="stat-card" id="card-cost">
            <div class="label">Today's Cost</div>
            <div class="value" id="stat-cost">$0.00</div>
            <div class="sub" id="stat-cost-alltime">All-time: $0.00</div>
        </div>
        <div class="stat-card">
            <div class="label">API Calls</div>
            <div class="value" id="stat-calls">0</div>
            <div class="sub" id="stat-calls-sub">today</div>
        </div>
        <div class="stat-card">
            <div class="label">Total Tokens</div>
            <div class="value" id="stat-tokens">0</div>
            <div class="sub" id="stat-tokens-sub">0 in / 0 out</div>
        </div>
        <div class="stat-card">
            <div class="label">Burn Rate</div>
            <div class="value" id="stat-burn">$0.00<span style="font-size:14px;color:var(--text-dim)">/hr</span></div>
            <div class="sub" id="stat-burn-sub">projected hourly</div>
        </div>
    </div>

    <!-- Charts -->
    <div class="chart-grid">
        <div class="chart-card">
            <h3>Cost Over Time (Today)</h3>
            <div class="chart-wrap">
                <canvas id="chart-timeline"></canvas>
            </div>
        </div>
        <div class="chart-card">
            <h3>Cost by Model</h3>
            <div class="chart-wrap">
                <canvas id="chart-models"></canvas>
            </div>
        </div>
    </div>

    <!-- Savings -->
    <div class="savings-section">
        <div class="savings-banner no-savings" id="savings-banner">
            <div>
                <div class="label">Potential Savings</div>
                <div class="amount" id="savings-amount">No data yet</div>
            </div>
        </div>
        <div class="table-card" id="savings-table-card" style="display:none">
            <h3>Optimization Recommendations</h3>
            <table>
                <thead>
                    <tr>
                        <th>Current Model</th>
                        <th>Recommended</th>
                        <th>Calls Affected</th>
                        <th>Current Cost</th>
                        <th>Optimized Cost</th>
                        <th>Savings</th>
                    </tr>
                </thead>
                <tbody id="savings-tbody"></tbody>
            </table>
        </div>
    </div>

    <!-- Recent calls -->
    <div class="table-card">
        <h3>Recent API Calls</h3>
        <table id="calls-table">
            <thead>
                <tr>
                    <th data-col="timestamp" class="sort-desc">Timestamp</th>
                    <th data-col="model">Model</th>
                    <th data-col="provider">Provider</th>
                    <th data-col="tokens">Tokens</th>
                    <th data-col="cost">Cost</th>
                    <th data-col="duration">Duration</th>
                </tr>
            </thead>
            <tbody id="calls-tbody"></tbody>
        </table>
        <div class="pagination" id="pagination">
            <button id="btn-prev" disabled>&laquo; Previous</button>
            <span class="page-info" id="page-info">Page 1</span>
            <button id="btn-next" disabled>Next &raquo;</button>
        </div>
    </div>

    <!-- Projections -->
    <div class="projections-grid" id="projections-grid">
        <div class="proj-card">
            <div class="proj-label">Today</div>
            <div class="proj-value" id="proj-today">$0.00</div>
        </div>
        <div class="proj-card">
            <div class="proj-label">This Week (projected)</div>
            <div class="proj-value" id="proj-week">$0.00</div>
        </div>
        <div class="proj-card">
            <div class="proj-label">This Month (projected)</div>
            <div class="proj-value" id="proj-month">$0.00</div>
        </div>
        <div class="proj-card optimized">
            <div class="proj-label">Optimized Monthly</div>
            <div class="proj-value" id="proj-optimized">$0.00</div>
        </div>
    </div>

    <footer>
        spent -- see what your AI really costs | auto-refreshing every 5 seconds
    </footer>
</div>

<script>
// -----------------------------------------------------------------------
// State
// -----------------------------------------------------------------------
let callsData = [];
let currentPage = 0;
const pageSize = 10;
let sortCol = 'timestamp';
let sortAsc = false;

let timelineChart = null;
let modelChart = null;

const CHART_COLORS = ['#58a6ff','#3fb950','#d29922','#f85149','#bc8cff','#79c0ff',
                       '#f0883e','#a5d6ff','#7ee787','#ffa657','#ff7b72','#d2a8ff'];

// -----------------------------------------------------------------------
// Formatting helpers
// -----------------------------------------------------------------------
function fmtCost(v) {
    if (v === null || v === undefined) return '$0.00';
    if (v < 0.01) return '$' + v.toFixed(4);
    if (v < 1) return '$' + v.toFixed(3);
    return '$' + v.toFixed(2);
}

function fmtTokens(n) {
    if (n === null || n === undefined) return '0';
    return n.toLocaleString();
}

function fmtDuration(ms) {
    if (!ms) return '--';
    if (ms < 1000) return ms + 'ms';
    return (ms / 1000).toFixed(1) + 's';
}

function fmtTime(ts) {
    if (!ts) return '--';
    try {
        const d = new Date(ts);
        return d.toLocaleTimeString([], {hour:'2-digit', minute:'2-digit', second:'2-digit'});
    } catch { return ts; }
}

function detectProvider(model) {
    if (!model) return '';
    if (model.startsWith('gpt-') || model.startsWith('o1') || model.startsWith('o3') || model.startsWith('o4')) return 'openai';
    if (model.startsWith('claude')) return 'anthropic';
    if (model.startsWith('gemini')) return 'google';
    if (model.startsWith('deepseek')) return 'deepseek';
    if (model.startsWith('mistral') || model.startsWith('codestral')) return 'mistral';
    if (model.startsWith('llama') || model.startsWith('mixtral')) return 'groq';
    return '';
}

function costClass(v) {
    if (v < 1) return 'cost-green';
    if (v < 10) return 'cost-yellow';
    return 'cost-red';
}

// -----------------------------------------------------------------------
// Chart initialization
// -----------------------------------------------------------------------
function initCharts() {
    Chart.defaults.color = '#8b949e';
    Chart.defaults.borderColor = '#30363d';
    Chart.defaults.font.family = "-apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif";

    const timeCtx = document.getElementById('chart-timeline').getContext('2d');
    timelineChart = new Chart(timeCtx, {
        type: 'line',
        data: { labels: [], datasets: [{ label: 'Cost ($)', data: [], borderColor: '#58a6ff', backgroundColor: 'rgba(88,166,255,0.08)', fill: true, tension: 0.35, pointRadius: 4, pointHoverRadius: 7, pointBackgroundColor: '#58a6ff', pointBorderColor: '#0d1117', pointBorderWidth: 2 }] },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: { intersect: false, mode: 'index' },
            plugins: {
                legend: { display: false },
                tooltip: {
                    backgroundColor: '#161b22',
                    borderColor: '#30363d',
                    borderWidth: 1,
                    titleColor: '#e6edf3',
                    bodyColor: '#e6edf3',
                    padding: 12,
                    cornerRadius: 8,
                    callbacks: { label: function(ctx) { return fmtCost(ctx.parsed.y); } }
                }
            },
            scales: {
                x: { grid: { display: false }, ticks: { maxRotation: 45, font: { size: 11 } } },
                y: { grid: { color: 'rgba(48,54,61,0.5)' }, ticks: { callback: function(v) { return fmtCost(v); }, font: { size: 11 } }, beginAtZero: true }
            }
        }
    });

    const modelCtx = document.getElementById('chart-models').getContext('2d');
    modelChart = new Chart(modelCtx, {
        type: 'doughnut',
        data: { labels: [], datasets: [{ data: [], backgroundColor: CHART_COLORS, borderColor: '#161b22', borderWidth: 3, hoverBorderColor: '#0d1117' }] },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            cutout: '65%',
            plugins: {
                legend: { position: 'right', labels: { padding: 16, usePointStyle: true, pointStyle: 'circle', font: { size: 12 } } },
                tooltip: {
                    backgroundColor: '#161b22',
                    borderColor: '#30363d',
                    borderWidth: 1,
                    titleColor: '#e6edf3',
                    bodyColor: '#e6edf3',
                    padding: 12,
                    cornerRadius: 8,
                    callbacks: {
                        label: function(ctx) {
                            const v = ctx.parsed;
                            const total = ctx.dataset.data.reduce((a,b) => a + b, 0);
                            const pct = total > 0 ? ((v / total) * 100).toFixed(1) : 0;
                            return ctx.label + ': ' + fmtCost(v) + ' (' + pct + '%)';
                        }
                    }
                }
            }
        }
    });
}

// -----------------------------------------------------------------------
// Update functions
// -----------------------------------------------------------------------
function updateStats(stats) {
    // Cost card
    const costCard = document.getElementById('card-cost');
    costCard.className = 'stat-card ' + costClass(stats.total_cost);
    document.getElementById('stat-cost').textContent = fmtCost(stats.total_cost);
    document.getElementById('stat-cost-alltime').textContent = 'All-time: ' + fmtCost(stats.all_time_cost);

    // Calls
    document.getElementById('stat-calls').textContent = fmtTokens(stats.total_calls);

    // Tokens
    document.getElementById('stat-tokens').textContent = fmtTokens(stats.total_tokens);
    document.getElementById('stat-tokens-sub').textContent = fmtTokens(stats.total_input) + ' in / ' + fmtTokens(stats.total_output) + ' out';

    // Burn rate
    document.getElementById('stat-burn').innerHTML = fmtCost(stats.burn_rate) + '<span style="font-size:14px;color:var(--text-dim)">/hr</span>';

    // Timeline chart
    const hourlyLabels = Object.keys(stats.hourly || {}).map(function(k) {
        try { return k.split(' ')[1] || k; } catch(e) { return k; }
    });
    const hourlyData = Object.values(stats.hourly || {});

    timelineChart.data.labels = hourlyLabels;
    timelineChart.data.datasets[0].data = hourlyData;
    timelineChart.update('none');

    // Model chart
    const models = Object.entries(stats.by_model || {}).sort(function(a,b) { return b[1].cost - a[1].cost; });
    modelChart.data.labels = models.map(function(m) { return m[0]; });
    modelChart.data.datasets[0].data = models.map(function(m) { return m[1].cost; });
    modelChart.update('none');

    // Savings
    const savings = stats.savings || [];
    const totalSavings = stats.total_possible_savings || 0;
    const banner = document.getElementById('savings-banner');
    const savingsAmt = document.getElementById('savings-amount');
    const savingsTableCard = document.getElementById('savings-table-card');

    if (totalSavings > 0) {
        banner.className = 'savings-banner';
        savingsAmt.textContent = 'You could save ' + fmtCost(totalSavings) + ' today';
        savingsTableCard.style.display = 'block';

        const tbody = document.getElementById('savings-tbody');
        tbody.innerHTML = '';
        savings.forEach(function(s) {
            const fromProvider = detectProvider(s.from_model);
            const toProvider = detectProvider(s.to_model);
            const row = document.createElement('tr');
            row.innerHTML = '<td><span class="model-tag ' + fromProvider + '">' + s.from_model + '</span></td>' +
                '<td><span class="arrow">&rarr;</span><span class="model-tag ' + toProvider + '">' + s.to_model + '</span></td>' +
                '<td>' + s.calls_affected + '</td>' +
                '<td class="cost">' + fmtCost(s.current_cost) + '</td>' +
                '<td class="cost">' + fmtCost(s.optimized_cost) + '</td>' +
                '<td class="savings-amount">' + fmtCost(s.savings) + '</td>';
            tbody.appendChild(row);
        });
    } else if (stats.total_calls > 0) {
        banner.className = 'savings-banner no-savings';
        savingsAmt.textContent = 'Already using optimal models';
        savingsTableCard.style.display = 'none';
    } else {
        banner.className = 'savings-banner no-savings';
        savingsAmt.textContent = 'No data yet';
        savingsTableCard.style.display = 'none';
    }

    // Projections
    const proj = stats.projections || {};
    document.getElementById('proj-today').textContent = fmtCost(proj.today);
    document.getElementById('proj-week').textContent = fmtCost(proj.week);
    document.getElementById('proj-month').textContent = fmtCost(proj.month);
    document.getElementById('proj-optimized').textContent = fmtCost(proj.optimized_month);
}

function updateCalls(data) {
    callsData = data || [];
    sortAndRender();
}

function sortAndRender() {
    // Sort
    const sorted = [...callsData].sort(function(a, b) {
        let va, vb;
        switch(sortCol) {
            case 'timestamp': va = a.timestamp || ''; vb = b.timestamp || ''; break;
            case 'model': va = a.model || ''; vb = b.model || ''; break;
            case 'provider': va = a.provider || ''; vb = b.provider || ''; break;
            case 'tokens': va = (a.input_tokens||0)+(a.output_tokens||0); vb = (b.input_tokens||0)+(b.output_tokens||0); break;
            case 'cost': va = a.cost||0; vb = b.cost||0; break;
            case 'duration': va = a.duration_ms||0; vb = b.duration_ms||0; break;
            default: va = a.timestamp||''; vb = b.timestamp||'';
        }
        if (typeof va === 'string') {
            return sortAsc ? va.localeCompare(vb) : vb.localeCompare(va);
        }
        return sortAsc ? va - vb : vb - va;
    });

    // Paginate
    const totalPages = Math.max(Math.ceil(sorted.length / pageSize), 1);
    if (currentPage >= totalPages) currentPage = totalPages - 1;
    if (currentPage < 0) currentPage = 0;

    const start = currentPage * pageSize;
    const page = sorted.slice(start, start + pageSize);

    const tbody = document.getElementById('calls-tbody');
    tbody.innerHTML = '';

    if (page.length === 0) {
        const row = document.createElement('tr');
        row.innerHTML = '<td colspan="6" style="text-align:center;color:var(--text-dim);padding:32px">No API calls tracked today. Run <code>spent run python your_script.py</code> to get started.</td>';
        tbody.appendChild(row);
    } else {
        page.forEach(function(r) {
            const provider = detectProvider(r.model);
            const tokens = (r.input_tokens || 0) + (r.output_tokens || 0);
            const row = document.createElement('tr');
            row.innerHTML = '<td class="timestamp">' + fmtTime(r.timestamp) + '</td>' +
                '<td><span class="model-tag ' + provider + '">' + (r.model || '--') + '</span></td>' +
                '<td>' + (r.provider || provider || '--') + '</td>' +
                '<td class="tokens">' + fmtTokens(tokens) + '</td>' +
                '<td class="cost">' + fmtCost(r.cost) + '</td>' +
                '<td>' + fmtDuration(r.duration_ms) + '</td>';
            tbody.appendChild(row);
        });
    }

    // Pagination controls
    document.getElementById('btn-prev').disabled = currentPage <= 0;
    document.getElementById('btn-next').disabled = currentPage >= totalPages - 1;
    document.getElementById('page-info').textContent = 'Page ' + (currentPage + 1) + ' of ' + totalPages;

    // Sort indicators
    document.querySelectorAll('#calls-table th').forEach(function(th) {
        th.classList.remove('sort-asc', 'sort-desc');
        if (th.dataset.col === sortCol) {
            th.classList.add(sortAsc ? 'sort-asc' : 'sort-desc');
        }
    });
}

// -----------------------------------------------------------------------
// Event handlers
// -----------------------------------------------------------------------
document.getElementById('btn-prev').addEventListener('click', function() {
    if (currentPage > 0) { currentPage--; sortAndRender(); }
});

document.getElementById('btn-next').addEventListener('click', function() {
    currentPage++;
    sortAndRender();
});

document.querySelectorAll('#calls-table th[data-col]').forEach(function(th) {
    th.addEventListener('click', function() {
        const col = this.dataset.col;
        if (sortCol === col) {
            sortAsc = !sortAsc;
        } else {
            sortCol = col;
            sortAsc = col === 'timestamp' ? false : true;
        }
        currentPage = 0;
        sortAndRender();
    });
});

// -----------------------------------------------------------------------
// Data fetching
// -----------------------------------------------------------------------
async function fetchData() {
    try {
        const [statsRes, callsRes] = await Promise.all([
            fetch('/api/stats'),
            fetch('/api/today')
        ]);
        const stats = await statsRes.json();
        const calls = await callsRes.json();

        updateStats(stats);
        updateCalls(calls);

        document.getElementById('last-update').textContent = 'Updated ' + new Date().toLocaleTimeString();
    } catch (err) {
        console.error('Fetch error:', err);
    }
}

// -----------------------------------------------------------------------
// Init
// -----------------------------------------------------------------------
initCharts();
fetchData();
setInterval(fetchData, 5000);
</script>
</body>
</html>"""


# ---------------------------------------------------------------------------
# HTTP request handler
# ---------------------------------------------------------------------------

class DashboardHandler(BaseHTTPRequestHandler):
    """Handles all dashboard HTTP requests."""

    storage: Storage  # set on the class before serving

    def do_GET(self) -> None:
        path = self.path.split("?")[0]

        if path == "/":
            self._respond_html(DASHBOARD_HTML)
        elif path == "/api/stats":
            self._respond_json(_build_stats(self.storage))
        elif path == "/api/today":
            self._respond_json(_build_today(self.storage))
        elif path == "/api/sessions":
            self._respond_json(_build_sessions(self.storage))
        else:
            self._respond_not_found()

    def _respond_html(self, html: str) -> None:
        body = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(body)

    def _respond_json(self, data: Any) -> None:
        body = _safe_json(data).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _respond_not_found(self) -> None:
        body = b'{"error": "not found"}'
        self.send_response(404)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: Any) -> None:
        """Suppress default logging to keep terminal clean."""
        pass


# ---------------------------------------------------------------------------
# Server entry point
# ---------------------------------------------------------------------------

def run_server(port: int = DEFAULT_PORT, open_browser: bool = True) -> None:
    """Start the web dashboard server.

    Args:
        port: TCP port to listen on (default 5050).
        open_browser: Open the dashboard URL in the default browser.
    """
    storage = Storage()
    DashboardHandler.storage = storage

    server = HTTPServer(("127.0.0.1", port), DashboardHandler)
    url = f"http://localhost:{port}"

    print(f"\n  spent web dashboard")
    print(f"  -------------------")
    print(f"  Running at:  {url}")
    print(f"  Database:    {storage.db_path}")
    print(f"  Press Ctrl+C to stop\n")

    if open_browser:
        threading.Timer(0.5, webbrowser.open, args=[url]).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  Dashboard stopped.")
        server.server_close()
