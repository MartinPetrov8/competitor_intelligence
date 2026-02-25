#!/usr/bin/env python3
"""
export_static.py — Generate a self-contained static HTML dashboard
from competitor_data.db. No server needed. All data baked in.

Usage:
    python export_static.py
    python export_static.py --output /path/to/output.html
    python export_static.py --db /path/to/other.db

Output: dashboard_YYYY-MM-DD.html (or --output path)
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

# ── Config ─────────────────────────────────────────────────────────────────
DEFAULT_DB   = Path(__file__).parent / "competitor_data.db"
SCRIPT_DIR   = Path(__file__).parent
GENERATED_AT = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
TODAY        = datetime.now(timezone.utc).strftime("%Y-%m-%d")


# ── DB helpers ──────────────────────────────────────────────────────────────
def load_data(db_path: Path) -> dict:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    def q(sql, params=()):
        return [dict(r) for r in conn.execute(sql, params).fetchall()]

    competitors = q("SELECT id, domain, base_url FROM competitors ORDER BY domain")

    prices_v2 = q("""
        SELECT c.domain AS competitor, p.scrape_date, p.main_price,
               p.currency, p.addons, p.source_url
        FROM prices_v2 p
        JOIN competitors c ON c.id = p.competitor_id
        ORDER BY p.scrape_date DESC, c.domain
    """)
    # parse addons JSON
    for row in prices_v2:
        try:
            row["addons"] = json.loads(row["addons"]) if row["addons"] else []
        except Exception:
            row["addons"] = []

    reviews_tp = q("""
        SELECT c.domain AS competitor, r.scrape_date, r.overall_rating,
               COALESCE(r.review_count, r.total_reviews) AS total_reviews,
               r.source_url
        FROM reviews_trustpilot r
        JOIN competitors c ON c.id = r.competitor_id
        ORDER BY r.scrape_date DESC, c.domain
    """)

    reviews_g = q("""
        SELECT c.domain AS competitor, r.scrape_date, r.overall_rating,
               r.total_reviews, r.source_url
        FROM reviews_google r
        JOIN competitors c ON c.id = r.competitor_id
        ORDER BY r.scrape_date DESC, c.domain
    """)

    diffs = q("""
        SELECT c.domain AS competitor, d.diff_date, d.page_type,
               d.diff_text, d.additions_count, d.removals_count
        FROM diffs d
        JOIN competitors c ON c.id = d.competitor_id
        ORDER BY d.diff_date DESC, c.domain
    """)

    ab_tests = q("""
        SELECT c.domain AS competitor, a.scrape_date, a.page_url,
               a.tool_name, a.detected, a.evidence
        FROM ab_tests a
        JOIN competitors c ON c.id = a.competitor_id
        ORDER BY a.scrape_date DESC, c.domain
    """)

    conn.close()
    return {
        "competitors": competitors,
        "prices_v2": prices_v2,
        "reviews_trustpilot": reviews_tp,
        "reviews_google": reviews_g,
        "diffs": diffs,
        "ab_tests": ab_tests,
    }


# ── HTML generation ─────────────────────────────────────────────────────────
def render_html(data: dict) -> str:
    payload = json.dumps(data, ensure_ascii=False, default=str)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Competitor Intelligence — {TODAY}</title>
  <script src="https://cdn.jsdelivr.net/npm/chart.js@4/dist/chart.umd.min.js"></script>
  <style>
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}

    body {{
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      background: #f0f2f5;
      color: #1a1a2e;
      min-height: 100vh;
    }}

    /* ── Header ── */
    .header {{
      background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
      color: #fff;
      padding: 1rem 2rem;
      display: flex;
      align-items: center;
      gap: 1rem;
      box-shadow: 0 2px 8px rgba(0,0,0,.35);
    }}
    .header h1 {{ font-size: 1.35rem; font-weight: 700; letter-spacing: .02em; }}
    .header .subtitle {{ font-size: .8rem; opacity: .65; margin-top: .15rem; }}
    .header .logo {{ font-size: 1.6rem; }}
    .last-updated {{ margin-left: auto; font-size: .75rem; opacity: .7; white-space: nowrap; text-align: right; }}
    .static-badge {{
      background: rgba(255,255,255,.15);
      border: 1px solid rgba(255,255,255,.25);
      border-radius: 4px;
      padding: .15rem .45rem;
      font-size: .7rem;
      font-weight: 600;
      letter-spacing: .04em;
      margin-top: .2rem;
    }}

    /* ── Nav tabs ── */
    .tab-bar {{
      background: #fff;
      border-bottom: 2px solid #e2e8f0;
      display: flex;
      gap: 0;
      padding: 0 2rem;
      overflow-x: auto;
    }}
    .tab-btn {{
      padding: .75rem 1.25rem;
      border: none;
      background: transparent;
      cursor: pointer;
      font-size: .9rem;
      font-weight: 500;
      color: #64748b;
      border-bottom: 3px solid transparent;
      margin-bottom: -2px;
      transition: color .15s, border-color .15s;
      white-space: nowrap;
    }}
    .tab-btn:hover {{ color: #0f172a; }}
    .tab-btn.active {{ color: #2563eb; border-bottom-color: #2563eb; }}

    /* ── Main content ── */
    .content {{ padding: 1.5rem 2rem; max-width: 1400px; margin: 0 auto; }}

    /* ── Cards ── */
    .card {{
      background: #fff;
      border-radius: 10px;
      box-shadow: 0 1px 4px rgba(0,0,0,.07);
      overflow: hidden;
      margin-bottom: 1.25rem;
    }}
    .card-header {{
      padding: .9rem 1.25rem;
      font-weight: 700;
      font-size: .95rem;
      border-bottom: 1px solid #f1f5f9;
      display: flex;
      align-items: center;
      gap: .5rem;
    }}
    .card-body {{ padding: 1.25rem; }}

    /* ── Tables ── */
    .table-wrap {{ overflow-x: auto; }}
    table {{ width: 100%; border-collapse: collapse; font-size: .875rem; }}
    thead th {{
      background: #f8fafc;
      padding: .65rem 1rem;
      text-align: left;
      font-weight: 700;
      color: #475569;
      font-size: .8rem;
      text-transform: uppercase;
      letter-spacing: .04em;
      border-bottom: 2px solid #e2e8f0;
    }}
    tbody tr {{ border-bottom: 1px solid #f1f5f9; transition: background .1s; }}
    tbody tr:hover {{ background: #f8fafc; }}
    tbody td {{ padding: .65rem 1rem; color: #1e293b; }}

    /* ── Chips ── */
    .summary-bar {{
      display: flex;
      flex-wrap: wrap;
      gap: .75rem;
      margin-bottom: 1.25rem;
    }}
    .chip {{
      background: #fff;
      border-radius: 8px;
      padding: .75rem 1.1rem;
      box-shadow: 0 1px 4px rgba(0,0,0,.07);
      display: flex;
      flex-direction: column;
      gap: .2rem;
      flex: 1;
      min-width: 140px;
    }}
    .chip .chip-label {{ font-size: .72rem; font-weight: 600; color: #64748b; text-transform: uppercase; letter-spacing: .04em; }}
    .chip .chip-value {{ font-size: 1.35rem; font-weight: 800; color: #1e293b; }}
    .chip .chip-sub {{ font-size: .75rem; color: #94a3b8; }}

    /* ── Price badge ── */
    .price-badge {{ display: inline-flex; align-items: center; gap: .3rem; font-weight: 700; color: #15803d; }}
    .price-badge.high {{ color: #dc2626; }}
    .price-badge.mid  {{ color: #d97706; }}

    /* ── Competitor dot ── */
    .competitor-dot {{
      display: inline-block;
      width: 10px; height: 10px;
      border-radius: 50%;
      margin-right: .35rem;
    }}

    /* ── Badge ── */
    .badge {{ display: inline-block; padding: .15rem .5rem; border-radius: 999px; font-size: .72rem; font-weight: 700; }}
    .badge-green {{ background: #dcfce7; color: #15803d; }}
    .badge-gray  {{ background: #f1f5f9; color: #475569; }}
    .badge-blue  {{ background: #eff6ff; color: #2563eb; }}
    .badge-red   {{ background: #fef2f2; color: #dc2626; }}

    /* ── Chart container ── */
    .chart-container {{ position: relative; height: 300px; }}
    .charts-row {{
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 1.25rem;
      margin-bottom: 1.25rem;
    }}
    @media (max-width: 900px) {{ .charts-row {{ grid-template-columns: 1fr; }} }}

    /* ── Tab panels ── */
    .tab-panel {{ display: none; }}
    .tab-panel.active {{ display: block; }}

    /* ── Rating ── */
    .rating-stars {{ color: #f59e0b; font-weight: 700; letter-spacing: .05em; }}
    .rating-num   {{ font-weight: 800; color: #1e293b; }}

    /* ── Diff viewer ── */
    .diff-item {{
      border: 1px solid #e2e8f0;
      border-radius: 8px;
      margin-bottom: 1rem;
      overflow: hidden;
    }}
    .diff-item-header {{
      display: flex;
      align-items: center;
      gap: .75rem;
      padding: .65rem 1rem;
      background: #f8fafc;
      border-bottom: 1px solid #e2e8f0;
      flex-wrap: wrap;
    }}
    .diff-item-header .competitor-name {{ font-weight: 700; font-size: .875rem; display: flex; align-items: center; gap: .35rem; }}
    .diff-meta {{ font-size: .78rem; color: #64748b; }}
    .diff-counts {{ margin-left: auto; display: flex; gap: .4rem; }}
    .diff-add-count {{ color: #15803d; font-weight: 700; font-size: .78rem; }}
    .diff-rem-count {{ color: #dc2626; font-weight: 700; font-size: .78rem; }}
    .diff-body {{
      padding: .75rem;
      background: #0f172a;
      max-height: 500px;
      overflow-y: auto;
    }}
    .diff-pre {{
      font-family: "SFMono-Regular", "Fira Code", "Consolas", monospace;
      font-size: .78rem;
      line-height: 1.5;
      white-space: pre-wrap;
      word-break: break-word;
    }}
    .diff-line {{ display: block; padding: 0 .25rem; border-radius: 2px; }}
    .diff-line-add {{ background: rgba(21,128,61,.25); color: #86efac; }}
    .diff-line-rem {{ background: rgba(220,38,38,.2);  color: #fca5a5; }}
    .diff-line-hdr {{ color: #93c5fd; font-weight: 700; }}
    .diff-line-ctx {{ color: #94a3b8; }}
    .diff-no-changes {{ padding: .5rem 1rem; font-size: .82rem; color: #94a3b8; font-style: italic; }}


    /* ── Source tabs ── */
    .source-tabs {{ display: flex; gap: .5rem; margin-bottom: 1rem; }}
    .source-tab-btn {{
      padding: .35rem .85rem;
      border: 1.5px solid #e2e8f0;
      border-radius: 999px;
      background: #fff;
      cursor: pointer;
      font-size: .825rem;
      font-weight: 600;
      color: #64748b;
      transition: all .15s;
    }}
    .source-tab-btn.active {{ background: #2563eb; border-color: #2563eb; color: #fff; }}

    /* ── Section heading ── */
    .section-date-label {{
      font-size: .78rem;
      color: #94a3b8;
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: .04em;
      margin: 1.25rem 0 .5rem;
      padding: 0 .25rem;
    }}

    /* ── Empty state ── */
    .empty-state {{
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      padding: 3rem 1rem;
      gap: .75rem;
      color: #94a3b8;
    }}
    .empty-state .icon {{ font-size: 2.5rem; }}
    .empty-state .label {{ font-size: .9rem; font-weight: 500; }}

    /* ── Addon tags ── */
    .addon-tag {{
      display: inline-block;
      padding: .1rem .4rem;
      border-radius: 4px;
      font-size: .7rem;
      font-weight: 600;
      background: #f1f5f9;
      color: #475569;
      margin: .1rem;
    }}

    @media (max-width: 640px) {{
      .content {{ padding: 1rem; }}
      .header {{ padding: .75rem 1rem; }}
      .tab-bar {{ padding: 0 1rem; }}
    }}
  </style>
</head>
<body>

<!-- Header -->
<header class="header">
  <div class="logo">📊</div>
  <div>
    <h1 class="header">Competitor Intelligence Tracker</h1>
    <div class="subtitle">DummyVisaTicket — Daily monitoring dashboard</div>
  </div>
  <div class="last-updated">
    <div>Generated {GENERATED_AT}</div>
    <div class="static-badge">STATIC SNAPSHOT</div>
  </div>
</header>

<!-- Tab bar -->
<nav class="tab-bar" role="tablist">
  <button class="tab-btn active" data-tab="pricing"  role="tab">💰 Pricing</button>
  <button class="tab-btn"        data-tab="reviews"  role="tab">⭐ Reviews</button>
  <button class="tab-btn"        data-tab="diffs"    role="tab">🔄 Site Diffs</button>
  <button class="tab-btn"        data-tab="abtests"  role="tab">🧪 A/B Tests</button>
</nav>

<main class="content">
  <section class="tab-panel active" id="tab-pricing"></section>
  <section class="tab-panel"        id="tab-reviews"></section>
  <section class="tab-panel"        id="tab-diffs"></section>
  <section class="tab-panel"        id="tab-abtests"></section>
</main>

<script>
// ── Embedded data ──────────────────────────────────────────────────────────
const DATA = {payload};

// ── Colours ───────────────────────────────────────────────────────────────
const PALETTE = ['#2563eb','#16a34a','#dc2626','#9333ea','#d97706','#0891b2','#db2777','#65a30d'];
const colorMap = {{}};
function color(domain) {{
  if (!colorMap[domain]) {{
    colorMap[domain] = PALETTE[Object.keys(colorMap).length % PALETTE.length];
  }}
  return colorMap[domain];
}}

// Pre-assign colours in competitor order so they're stable
DATA.competitors.forEach(c => color(c.domain));

// ── Escape ────────────────────────────────────────────────────────────────
function esc(s) {{
  return String(s ?? '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}}

// ── Helpers ───────────────────────────────────────────────────────────────
function dot(domain) {{
  return `<span class="competitor-dot" style="background:${{color(domain)}}"></span>`;
}}
function priceBadge(amount, currency) {{
  if (amount == null) return '—';
  const p = parseFloat(amount);
  const cls = p > 30 ? 'high' : p > 15 ? 'mid' : '';
  return `<span class="price-badge ${{cls}}">${{currency || '$'}}${{p.toFixed(2)}}</span>`;
}}
function stars(rating) {{
  if (rating == null) return '';
  const full = Math.floor(rating);
  const half = (rating - full) >= 0.5 ? 1 : 0;
  const empty = 5 - full - half;
  return '★'.repeat(full) + (half ? '½' : '') + '☆'.repeat(empty);
}}

// ── Chart helpers ─────────────────────────────────────────────────────────
const chartInstances = {{}};
function mkChart(canvasId, labels, datasets, tickFn) {{
  if (chartInstances[canvasId]) chartInstances[canvasId].destroy();
  const ctx = document.getElementById(canvasId)?.getContext('2d');
  if (!ctx) return;
  chartInstances[canvasId] = new Chart(ctx, {{
    type: 'line',
    data: {{ labels, datasets }},
    options: {{
      responsive: true, maintainAspectRatio: false,
      interaction: {{ mode: 'index', intersect: false }},
      plugins: {{ legend: {{ position: 'top', labels: {{ usePointStyle: true, boxWidth: 10 }} }} }},
      scales: {{
        x: {{ grid: {{ color: '#f1f5f9' }}, ticks: {{ font: {{ size: 11 }}, maxRotation: 45 }} }},
        y: {{ grid: {{ color: '#f1f5f9' }}, ticks: {{ font: {{ size: 11 }}, callback: tickFn }}, beginAtZero: false }}
      }}
    }}
  }});
}}

function buildLineDatasets(rows, dateKey, valueKey, filterFn) {{
  const byComp = {{}};
  for (const r of rows) {{
    if (!filterFn(r)) continue;
    if (!byComp[r.competitor]) byComp[r.competitor] = {{}};
    const existing = byComp[r.competitor][r[dateKey]];
    if (existing === undefined) byComp[r.competitor][r[dateKey]] = parseFloat(r[valueKey]);
  }}
  const dates = [...new Set(rows.map(r => r[dateKey]).filter(Boolean))].sort();
  const datasets = Object.entries(byComp).map(([comp, byDate]) => ({{
    label: comp,
    data: dates.map(d => byDate[d] ?? null),
    borderColor: color(comp),
    backgroundColor: color(comp) + '22',
    fill: false, tension: 0.35, pointRadius: 4, pointHoverRadius: 6, spanGaps: true,
  }}));
  return {{ dates, datasets }};
}}

// ══════════════════════════════════════════════════════════════════════════
// PRICING TAB
// ══════════════════════════════════════════════════════════════════════════
function renderPricing() {{
  const el = document.getElementById('tab-pricing');

  const v2Prices = DATA.prices_v2.map(r => r.main_price).filter(p => p != null);
  const latestDates = [...new Set(DATA.prices_v2.map(r => r.scrape_date).filter(Boolean))].sort();
  const latestDate = latestDates[latestDates.length - 1] || '—';

  const chips = `
    <div class="summary-bar">
      <div class="chip"><div class="chip-label">Competitors</div><div class="chip-value">${{DATA.competitors.length}}</div><div class="chip-sub">tracked</div></div>
      <div class="chip"><div class="chip-label">Lowest price</div><div class="chip-value">${{v2Prices.length ? '$' + Math.min(...v2Prices).toFixed(2) : '—'}}</div><div class="chip-sub">across all</div></div>
      <div class="chip"><div class="chip-label">Highest price</div><div class="chip-value">${{v2Prices.length ? '$' + Math.max(...v2Prices).toFixed(2) : '—'}}</div><div class="chip-sub">across all</div></div>
      <div class="chip"><div class="chip-label">Last updated</div><div class="chip-value" style="font-size:.95rem;">${{esc(latestDate)}}</div><div class="chip-sub">most recent scrape</div></div>
    </div>`;

  // Current prices: latest record per competitor
  const compDomains = DATA.competitors.map(c => c.domain);
  const latestByComp = {{}};
  for (const r of DATA.prices_v2) {{
    if (!latestByComp[r.competitor] || r.scrape_date > latestByComp[r.competitor].scrape_date) {{
      latestByComp[r.competitor] = r;
    }}
  }}
  const matrixRows = compDomains.map(d => {{
    const r = latestByComp[d];
    return `<tr>
      <td>${{dot(d)}}${{esc(d)}}</td>
      <td>${{r ? priceBadge(r.main_price, r.currency) : '<span style="color:#94a3b8">No data</span>'}}</td>
      <td>${{r ? esc(r.scrape_date) : '—'}}</td>
      <td>${{r ? (r.addons || []).map(a => `<span class="addon-tag">${{esc(a.name)}}: ${{a.price != null ? '$'+parseFloat(a.price).toFixed(2) : '?'}}</span>`).join('') || '<span style="color:#94a3b8">—</span>' : '—'}}</td>
    </tr>`;
  }}).join('');

  const matrix = `
    <div class="card">
      <div class="card-header">💰 Current Prices <span class="badge badge-gray" style="margin-left:auto;">${{esc(latestDate)}}</span></div>
      <div class="card-body">
        <div class="table-wrap">
          <table>
            <thead><tr><th>Competitor</th><th>Price</th><th>Last Scraped</th><th>Add-ons</th></tr></thead>
            <tbody>${{matrixRows}}</tbody>
          </table>
        </div>
      </div>
    </div>`;

  // Price trend chart
  const {{ dates: trendDates, datasets: trendDS }} = buildLineDatasets(
    DATA.prices_v2, 'scrape_date', 'main_price', r => r.main_price != null
  );
  const trendChart = trendDates.length ? `
    <div class="card">
      <div class="card-header">📈 Price Trend</div>
      <div class="card-body">
        <div class="chart-container"><canvas id="chartPriceTrend"></canvas></div>
      </div>
    </div>` : '';

  el.innerHTML = chips + matrix + trendChart;

  if (trendDates.length) {{
    mkChart('chartPriceTrend', trendDates, trendDS, v => '$' + v.toFixed(2));
  }}
}}

// ══════════════════════════════════════════════════════════════════════════
// REVIEWS TAB
// ══════════════════════════════════════════════════════════════════════════
let activeReviewSource = 'trustpilot';

function renderReviewsContent(source) {{
  const rows = source === 'trustpilot' ? DATA.reviews_trustpilot : DATA.reviews_google;
  const container = document.getElementById('reviewsContent');

  if (!rows.length) {{
    container.innerHTML = `<div class="empty-state"><div class="icon">🔍</div><div class="label">No ${{source}} data available</div></div>`;
    return;
  }}

  // Latest ratings chips
  const latestDate = rows[0]?.scrape_date;
  const latest = rows.filter(r => r.scrape_date === latestDate);
  const chips = latest.map(r => `
    <div class="chip">
      <div class="chip-label">${{dot(r.competitor)}}${{esc(r.competitor)}}</div>
      <div class="chip-value"><span class="rating-stars">${{stars(r.overall_rating)}}</span> ${{r.overall_rating?.toFixed(1) ?? '—'}}</div>
      <div class="chip-sub">${{r.total_reviews != null ? r.total_reviews.toLocaleString() + ' reviews' : '—'}}</div>
    </div>`).join('');

  // Trend charts
  const {{ dates: ratingDates, datasets: ratingDS }} = buildLineDatasets(
    rows, 'scrape_date', 'overall_rating', r => r.overall_rating != null
  );
  const {{ dates: countDates, datasets: countDS }} = buildLineDatasets(
    rows, 'scrape_date', 'total_reviews', r => r.total_reviews != null
  );

  // Table
  const tableRows = rows.map(r => `<tr>
    <td>${{dot(r.competitor)}}${{esc(r.competitor)}}</td>
    <td>${{esc(r.scrape_date)}}</td>
    <td><span class="rating-num">${{r.overall_rating?.toFixed(1) ?? '—'}}</span> <span class="rating-stars">${{stars(r.overall_rating)}}</span></td>
    <td>${{r.total_reviews != null ? Number(r.total_reviews).toLocaleString() : '—'}}</td>
    <td><a href="${{esc(r.source_url || '#')}}" target="_blank" style="color:#2563eb;font-size:.8rem;">link ↗</a></td>
  </tr>`).join('');

  container.innerHTML = `
    <div class="summary-bar">${{chips}}</div>
    ${{ratingDates.length ? `
    <div class="charts-row">
      <div class="card" style="margin-bottom:0;">
        <div class="card-header">⭐ Rating Trend</div>
        <div class="card-body"><div class="chart-container"><canvas id="chartReviewRating"></canvas></div></div>
      </div>
      <div class="card" style="margin-bottom:0;">
        <div class="card-header">💬 Review Count Trend</div>
        <div class="card-body"><div class="chart-container"><canvas id="chartReviewCount"></canvas></div></div>
      </div>
    </div><div style="margin-bottom:1.25rem;"></div>` : ''}}
    <div class="card">
      <div class="card-header">📋 All Ratings <span class="badge badge-gray" style="margin-left:auto;">${{rows.length}} rows</span></div>
      <div class="card-body">
        <div class="table-wrap">
          <table>
            <thead><tr><th>Competitor</th><th>Date</th><th>Rating</th><th>Reviews</th><th>Source</th></tr></thead>
            <tbody>${{tableRows}}</tbody>
          </table>
        </div>
      </div>
    </div>`;

  if (ratingDates.length) {{
    mkChart('chartReviewRating', ratingDates, ratingDS, v => v.toFixed(1) + '★');
    mkChart('chartReviewCount',  countDates,  countDS,  v => v.toLocaleString());
  }}
}}

function renderReviews() {{
  const el = document.getElementById('tab-reviews');
  el.innerHTML = `
    <div class="source-tabs" id="reviewsSourceTabs">
      <button class="source-tab-btn active" data-source="trustpilot">Trustpilot</button>
      <button class="source-tab-btn" data-source="google">Google</button>
    </div>
    <div id="reviewsContent"></div>`;

  document.querySelectorAll('.source-tab-btn').forEach(btn => {{
    btn.addEventListener('click', () => {{
      activeReviewSource = btn.dataset.source;
      document.querySelectorAll('.source-tab-btn').forEach(b => b.classList.toggle('active', b.dataset.source === activeReviewSource));
      renderReviewsContent(activeReviewSource);
    }});
  }});

  renderReviewsContent(activeReviewSource);
}}

// ══════════════════════════════════════════════════════════════════════════
// DIFFS TAB
// ══════════════════════════════════════════════════════════════════════════
function renderDiffLine(line) {{
  const e = esc(line);
  if (line.startsWith('+++') || line.startsWith('---')) return `<span class="diff-line diff-line-hdr">${{e}}</span>`;
  if (line.startsWith('@@'))  return `<span class="diff-line diff-line-hdr">${{e}}</span>`;
  if (line.startsWith('+'))   return `<span class="diff-line diff-line-add">${{e}}</span>`;
  if (line.startsWith('-'))   return `<span class="diff-line diff-line-rem">${{e}}</span>`;
  return `<span class="diff-line diff-line-ctx">${{e}}</span>`;
}}

function renderDiffs() {{
  const el = document.getElementById('tab-diffs');

  if (!DATA.diffs.length) {{
    el.innerHTML = `<div class="card"><div class="card-body"><div class="empty-state"><div class="icon">🔍</div><div class="label">No site changes detected yet</div></div></div></div>`;
    return;
  }}

  // Only show entries where something actually changed
  const changed = DATA.diffs.filter(r => (r.additions_count > 0 || r.removals_count > 0));

  if (!changed.length) {{
    el.innerHTML = `<div class="card"><div class="card-body"><div class="empty-state"><div class="icon">✅</div><div class="label">No changes detected across all competitors</div></div></div></div>`;
    return;
  }}

  const items = changed.map((r, i) => {{
    // Only render + and - lines from the diff (skip context lines and headers)
    const relevantLines = (r.diff_text || '').split('\\n').filter(line =>
      line.startsWith('+') || line.startsWith('-')
    );
    const diffHtml = relevantLines.length
      ? `<div class="diff-body"><pre class="diff-pre">${{relevantLines.map(renderDiffLine).join('\\n')}}</pre></div>`
      : '';

    return `<div class="diff-item">
      <div class="diff-item-header">
        <div class="competitor-name">${{dot(r.competitor)}}${{esc(r.competitor)}}</div>
        <span class="diff-meta">${{esc(r.diff_date)}} · ${{esc(r.page_type || 'homepage')}}</span>
        <div class="diff-counts">
          <span class="diff-add-count">+${{r.additions_count}} added</span>
          <span class="diff-rem-count">-${{r.removals_count}} removed</span>
        </div>
      </div>
      ${{diffHtml}}
    </div>`;
  }}).join('');

  el.innerHTML = `
    <div class="card">
      <div class="card-header">🔄 Website Changes <span class="badge badge-gray" style="margin-left:auto;">${{changed.length}} change${{changed.length !== 1 ? 's' : ''}}</span></div>
      <div class="card-body">${{items}}</div>
    </div>`;
}}

// ══════════════════════════════════════════════════════════════════════════
// A/B TESTS TAB
// ══════════════════════════════════════════════════════════════════════════
function renderAbTests() {{
  const el = document.getElementById('tab-abtests');

  if (!DATA.ab_tests.length) {{
    el.innerHTML = `<div class="card"><div class="card-body"><div class="empty-state"><div class="icon">🧪</div><div class="label">No A/B tests detected yet</div></div></div></div>`;
    return;
  }}

  const rows = DATA.ab_tests.map(r => `<tr>
    <td>${{dot(r.competitor)}}${{esc(r.competitor)}}</td>
    <td>${{esc(r.scrape_date)}}</td>
    <td style="max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${{esc(r.page_url)}}</td>
    <td>${{esc(r.tool_name || '—')}}</td>
    <td>${{r.detected ? '<span class="badge badge-red">Detected</span>' : '<span class="badge badge-gray">None</span>'}}</td>
    <td style="max-width:250px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${{esc(r.evidence || '—')}}</td>
  </tr>`).join('');

  el.innerHTML = `
    <div class="card">
      <div class="card-header">🧪 A/B Test Detection <span class="badge badge-gray" style="margin-left:auto;">${{DATA.ab_tests.length}} records</span></div>
      <div class="card-body">
        <div class="table-wrap">
          <table>
            <thead><tr><th>Competitor</th><th>Date</th><th>URL</th><th>Tool</th><th>Detected</th><th>Evidence</th></tr></thead>
            <tbody>${{rows}}</tbody>
          </table>
        </div>
      </div>
    </div>`;
}}

// ══════════════════════════════════════════════════════════════════════════
// TAB SWITCHING
// ══════════════════════════════════════════════════════════════════════════
const rendered = {{}};

function switchTab(name) {{
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.toggle('active', b.dataset.tab === name));
  document.querySelectorAll('.tab-panel').forEach(p => p.classList.toggle('active', p.id === 'tab-' + name));

  if (!rendered[name]) {{
    rendered[name] = true;
    if (name === 'pricing')  renderPricing();
    if (name === 'reviews')  renderReviews();
    if (name === 'diffs')    renderDiffs();
    if (name === 'abtests')  renderAbTests();
  }}
}}

// ── Init ──────────────────────────────────────────────────────────────────
document.querySelectorAll('.tab-btn').forEach(btn => {{
  btn.addEventListener('click', () => switchTab(btn.dataset.tab));
}});

switchTab('pricing');
</script>
</body>
</html>
"""


# ── Entry point ─────────────────────────────────────────────────────────────
def main() -> None:
    parser = argparse.ArgumentParser(description="Export competitor dashboard as static HTML")
    parser.add_argument("--db",     default=str(DEFAULT_DB),                            help="Path to SQLite DB")
    parser.add_argument("--output", default=str(SCRIPT_DIR / f"dashboard_{TODAY}.html"), help="Output HTML path")
    args = parser.parse_args()

    db_path  = Path(args.db)
    out_path = Path(args.output)

    if not db_path.exists():
        raise SystemExit(f"DB not found: {db_path}")

    print(f"📦 Loading data from {db_path}…")
    data = load_data(db_path)

    total_rows = sum(len(v) for v in data.values() if isinstance(v, list))
    print(f"   competitors: {len(data['competitors'])}")
    print(f"   prices:      {len(data['prices_v2'])} v2")
    print(f"   reviews:     {len(data['reviews_trustpilot'])} TP / {len(data['reviews_google'])} Google")
    print(f"   diffs:       {len(data['diffs'])}")
    print(f"   ab_tests:    {len(data['ab_tests'])}")
    print(f"   total rows:  {total_rows}")

    print(f"\n🔨 Rendering HTML…")
    html = render_html(data)

    out_path.write_text(html, encoding="utf-8")
    size_kb = out_path.stat().st_size // 1024
    print(f"✅ Saved: {out_path}  ({size_kb} KB)")


if __name__ == "__main__":
    main()
