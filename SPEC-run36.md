# Run #36 — Competitor Intelligence Tracker: Finish the Product

**Repo:** https://github.com/MartinPetrov8/competitor_intelligence  
**Dashboard (live):** https://competitor-intelligence-pxin.onrender.com (password: dummyvisa2026)  
**Branch:** feature/v2-frontend-and-polish  
**Push target:** main (Render auto-deploys on push to main)

---

## Context — What's Already Done

The backend is complete and working:
- `prices_v2` table: 1 clean row per competitor per day, main price + addons JSON
- `products_v2` table: boolean matrix (one_way/round_trip/hotel/visa_letter) per competitor
- Trustpilot reviews: working (4/5 competitors, vizafly not on TP)
- Flask dashboard at `dashboard/server.py` with API endpoints serving v2 data
- Render deployed, auto-deploys on push to main

**Current competitors tracked:**
- onwardticket.com ($16 main price)
- bestonwardticket.com ($14 main price)
- dummyticket.com (N/A)
- dummy-tickets.com ($5 main price)
- vizafly.com (N/A)

**Known broken test:**
- `tests/test_products_scraper.py` fails to import: `extract_product_records` not found in `scrapers/products.py` — fix this import error first, it blocks test suite collection.

---

## Stories

### S-01: Fix test suite + dashboard frontend redesign (HIGH — blocks everything)

**File to update:** `dashboard/templates/index.html` and `dashboard/static/`  
**Also fix:** `tests/test_products_scraper.py` import error before running tests

The HTML/JS still renders v1-style. Rebuild it to match this spec:

**Pricing tab:**
- One row per competitor, showing: name | main price | price change vs yesterday (green ▲ / red ▼ / — neutral) | addons (collapsible accordion)
- Line chart over time using Chart.js (CDN link, no npm needed)
- Data comes from existing `/api/pricing` endpoint

**Products tab:**
- 5×4 matrix: rows=competitors, cols=one_way/round_trip/hotel/visa_letter
- Each cell: ✅ or ❌
- Data comes from existing `/api/products` endpoint

**Reviews tab:**
- One card per competitor: name | Trustpilot score (N/A if missing) | Google score (N/A if missing) | review count | last updated
- Data comes from existing `/api/reviews` endpoint

**Site Changes tab:**
- Shows diffs categorized by emoji: 💰 price_change | 📦 product_change | 📝 copy_change | 🎨 layout_change
- Hide competitors with zero changes today
- Show "No changes detected today" message when all empty
- Data comes from existing `/api/site-changes` endpoint

**Acceptance criteria:**
- `pytest tests/ -q --ignore=tests/test_products_scraper.py` passes (all non-scraper tests)
- Dashboard renders all 4 tabs without errors
- Chart.js line chart visible on pricing tab
- Product matrix shows ✅/❌ for all 5 competitors

---

### S-02: Site diff categorization (MEDIUM)

**File:** `scrapers/snapshots.py`

Add automatic categorization to the `diffs` table:
1. Add columns `change_categories` (JSON array TEXT) and `change_summary` (TEXT) to `diffs` table — migration must be safe (IF NOT EXISTS / ALTER TABLE if not exists pattern)
2. When storing a diff, classify the change text using these regex rules:
   - `price_change`: matches price patterns (`\$\d+`, `price`, `cost`, `fee`)
   - `product_change`: matches product words (`one.way`, `round.trip`, `hotel`, `visa`)
   - `copy_change`: any text change not matching above categories
   - `layout_change`: matches HTML structural tags (`<div`, `<section`, `<nav`, `class=`)
3. Store as JSON array e.g. `["price_change", "copy_change"]`
4. `change_summary` = first 120 chars of the diff text

**Acceptance criteria:**
- `diffs` table has `change_categories` and `change_summary` columns
- Running `run_daily.py` produces non-null `change_categories` for at least 1 competitor
- Site Changes tab dashboard uses categories for emoji display

---

### S-03: Google Reviews scraper fix (LOW)

**File:** `scrapers/reviews_google.py`

Currently returns 0 rows. The Google Knowledge Panel parsing is broken.

Fix approach:
1. Try fetching `https://www.google.com/search?q={competitor}+reviews` with a real User-Agent header
2. Parse for the rating pattern: look for `aria-label` containing "Rated X out of 5" or the JSON-LD structured data
3. If Google blocks: use the SerpAPI-style fallback — just store `rating=None, count=None` gracefully rather than crashing
4. At minimum, the scraper must not throw exceptions and must return a list (possibly empty)

**Acceptance criteria:**
- `reviews_google.py` runs without exceptions
- At least 1 competitor returns a non-None rating OR all return None gracefully
- No test regressions

---

### S-04: Daily cron setup (MEDIUM)

Set up an OpenClaw cron job to run `run_daily.py` every day at 06:00 UTC.

**The cron must:**
- Run: `bash -c "cd /home/node/.openclaw/workspace/projects/competitor-tracker && source venv/bin/activate && PYTHONPATH=. python3 run_daily.py"`
- Schedule: `0 6 * * *` (06:00 UTC daily)
- Use the OpenClaw cron system — add to `/home/node/.openclaw/cron/jobs.json`

Format for jobs.json entry:
```json
{
  "id": "competitor-tracker-daily",
  "name": "Competitor Tracker Daily Scrape",
  "schedule": "0 6 * * *",
  "command": "bash -c 'cd /home/node/.openclaw/workspace/projects/competitor-tracker && source venv/bin/activate && PYTHONPATH=. python3 run_daily.py'",
  "enabled": true
}
```

**Acceptance criteria:**
- Entry exists in `/home/node/.openclaw/cron/jobs.json`
- `openclaw cron list` shows the job

---

## Technical Notes

**How to run tests:**
```bash
cd /home/node/.openclaw/workspace/projects/competitor-tracker
bash -c "source venv/bin/activate && PYTHONPATH=. pytest tests/ -q --ignore=tests/test_products_scraper.py"
```

**How to start dashboard locally:**
```bash
bash -c "source venv/bin/activate && PYTHONPATH=. python3 dashboard/server.py"
# Serves on port 3001
```

**Push to deploy:**
```bash
git push origin feature/v2-frontend-and-polish
# Then open PR to main — Render auto-deploys on merge
```

**Key files:**
- `dashboard/templates/index.html` — main template to rewrite
- `dashboard/static/` — JS/CSS
- `dashboard/server.py` — Flask routes (already updated for v2)
- `scrapers/snapshots.py` — add categorization
- `scrapers/reviews_google.py` — fix or gracefully degrade
- `tests/` — must pass before PR

---

## Definition of Done

- [ ] All 4 stories complete
- [ ] `pytest tests/ -q --ignore=tests/test_products_scraper.py` passes
- [ ] Dashboard renders correctly on https://competitor-intelligence-pxin.onrender.com
- [ ] Cron job in jobs.json
- [ ] PR merged to main
- [ ] No regressions in existing scrapers
