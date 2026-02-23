# Handoff — Competitor Intelligence Tracker

**Date:** 2026-02-23  
**Status:** MVP backend working, frontend redesign pending  
**Repo:** https://github.com/MartinPetrov8/competitor_intelligence  
**Dashboard:** https://competitor-intelligence-pxin.onrender.com (password: dummyvisa2026)

---

## What's Done ✅

- `prices_v2` table: 1 clean row per competitor per day, main price + addons JSON, no JS noise
- `products_v2` table: boolean matrix (one_way/round_trip/hotel/visa_letter) per competitor
- Trustpilot reviews: working (4/5 competitors, vizafly not on TP)
- Dashboard API endpoints updated to serve v2 data
- Render deployed, auto-deploys on push to main

**Current data (2026-02-23):**
| Competitor | Main Price | One-way | Round-trip | Hotel | Visa |
|---|---|---|---|---|---|
| onwardticket.com | $16 | ✅ | ✅ | ❌ | ❌ |
| bestonwardticket.com | $14 | ✅ | ✅ | ❌ | ✅ |
| dummyticket.com | N/A | ✅ | ✅ | ✅ | ✅ |
| dummy-tickets.com | $5 | ✅ | ✅ | ✅ | ✅ |
| vizafly.com | N/A | ✅ | ❌ | ✅ | ✅ |

---

## What Needs Doing ❌

### 1. Dashboard frontend redesign (HIGH — user-facing)
The dashboard HTML/JS still renders v1-style tables. Needs updating to match SPEC-v2.md:

**Pricing tab:**
- One row per competitor
- Green/red highlight if price changed vs yesterday
- Add-ons collapsible accordion
- Line chart over time (Chart.js)

**Products tab:**
- 5×4 comparison matrix
- ✅ + price or ❌ per cell
- No free text

**Reviews tab:**
- Combined Trustpilot + Google per competitor
- N/A for missing data

**Site Changes tab:**
- Categorized diffs only (💰📦📝🎨)
- Hide competitors with no changes
- "No changes today" message when empty

### 2. Site diff categorization (MEDIUM)
File: `scrapers/snapshots.py`  
Add `change_categories` (JSON array) and `change_summary` (TEXT) columns to `diffs` table.  
Classify diffs: price_change / product_change / copy_change / layout_change using regex.

### 3. Google Reviews scraper (LOW)
File: `scrapers/reviews_google.py`  
Currently returns 0 rows. Google Knowledge Panel parsing needs fixing.  
At least 1 competitor should return a rating.

### 4. Daily cron (MEDIUM)
Set up OpenClaw cron for `run_daily.py` to run every morning at 06:00 UTC.

---

## How to Run Locally

```bash
cd /home/node/.openclaw/workspace/projects/competitor-tracker
source venv/bin/activate
PYTHONPATH=. python3 run_daily.py          # full scrape
PYTHONPATH=. python3 dashboard/server.py   # start dashboard on port 3001
```

## How to Run Tests

```bash
source venv/bin/activate
PYTHONPATH=. pytest tests/ -x -q
```

## Key Files
- `SPEC-v2.md` — full requirements spec
- `scrapers/pricing.py` — v2 pricing scraper (clean, working)
- `scrapers/products.py` — v2 products scraper (clean, working)
- `dashboard/server.py` — Flask app, API endpoints
- `dashboard/templates/` — HTML templates to update
- `dashboard/static/` — JS/CSS to update
