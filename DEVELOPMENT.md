# Development Notes

This document covers architecture decisions, known issues, roadmap, and build history for the Competitor Intelligence Tracker.

---

## Architecture Decisions

### Why SQLite?
All data is append-only (new rows per scrape date). SQLite is sufficient for a single-writer, low-volume use case like daily scraping of 5 competitors. Upgrading to Postgres is straightforward if multi-user access or concurrent writes become necessary.

### Historical comparison design
Every scraper writes rows tagged with `scrape_date` (YYYY-MM-DD) and `scraped_at` (ISO timestamp). This means:
- Full history is preserved — nothing is overwritten
- Price trends over time are queryable with a simple `GROUP BY scrape_date`
- Diffs are computed by comparing today's snapshot hash against yesterday's

### Why Flask over FastAPI?
Minimal dependencies, fast to prototype, no async complexity needed for a dashboard that serves one user. If the dashboard needs to scale or expose a proper API, FastAPI is the natural migration target.

### Scraper isolation
Each scraper module is self-contained: it opens its own DB connection, writes its own table, and closes cleanly. A failure in one module does not abort others — the daily runner (`run_daily.py`) catches exceptions per-module and continues.

---

## Competitors Tracked

| Domain | Notes |
|---|---|
| onwardticket.com | Main reference competitor. Uses Next.js. Trustpilot: 4.8★ / 526 reviews. |
| bestonwardticket.com | WordPress + Gravity Forms. Price: ~$14. |
| dummyticket.com | |
| dummy-tickets.com | |
| vizafly.com | |

---

## Known Issues & Fixes In Progress

### Trustpilot scraper — 0 rows (bug-fix run #32, 2026-02-23)
**Symptom:** `reviews_trustpilot` table returns 0 rows after first scrape.  
**Root cause:** Trustpilot pages are Next.js SSR apps. Rating data is embedded in a `<script id="__NEXT_DATA__">` JSON blob, not in visible HTML. The original scraper was looking at the wrong fields.  
**Fix:** Parse `__NEXT_DATA__` JSON, extract `trustScore` and `numberOfReviews` directly.  
**Status:** Fix in progress via Antfarm bug-fix run #32.

### Google Reviews scraper — 0 rows (bug-fix run #32, 2026-02-23)
**Symptom:** `reviews_google` table returns 0 rows.  
**Root cause:** Under investigation in run #32.  
**Status:** Fix in progress.

### Pricing scraper — raw JS/HTML noise in raw_text column
**Symptom:** Some rows in `prices` table contain thousands of characters of JavaScript code instead of a clean price string.  
**Root cause:** The scraper extracts all text nodes near price patterns without filtering out script content.  
**Fix:** Skip rows where `raw_text` length > 500 chars or contains known JS patterns (`self.__next_f.push`, `<![CDATA[`, `jQuery(document)`).  
**Status:** Fix in progress via Antfarm bug-fix run #32.

### A/B test detection — 0 rows (by design)
**Symptom:** `ab_tests` table always empty.  
**Root cause:** None of the 5 tracked competitors currently use detectable A/B testing frameworks (Optimizely, VWO, Google Optimize, LaunchDarkly, etc.). This is expected behaviour — these are small businesses.  
**Status:** Not a bug. Will populate if a competitor adds A/B tooling.

### Website diffs — 0 rows (day 1 by design)
**Symptom:** `diffs` table empty after first scrape.  
**Root cause:** Diffs require two consecutive snapshots to compare. Day 1 only has one snapshot per competitor.  
**Status:** Will populate automatically after day 2 scrape.

---

## Dashboard Views (Planned)

| View | Status | Notes |
|---|---|---|
| Pricing table + trends | ✅ Built | Shows price by competitor over time |
| Product comparison matrix | ✅ Built | Side-by-side service offerings |
| Diff viewer | ✅ Built | Shows HTML diffs between scrape dates |
| Review metrics (Trustpilot/Google) | ✅ Built | Needs scraper fix to populate |
| Date picker | ✅ Built | Filter all views by scrape date |

### Planned improvements
- [ ] Price change alerts (notify when a competitor changes price)
- [ ] Slack/Telegram notification when significant diff detected
- [ ] Mobile-responsive dashboard layout
- [ ] Export to CSV button

---

## Daily Cron Setup

The scraper should run once daily. Recommended cron (Sofia timezone, 08:00):

```bash
# Add to crontab (crontab -e)
0 6 * * * cd /path/to/competitor-tracker && bash -c "source venv/bin/activate && PYTHONPATH=. python3 run_daily.py >> logs/cron.log 2>&1"
```

Or via OpenClaw cron (already configured on the host):
```
Daily run: 06:00 UTC via openclaw cron
```

---

## Build History

| Date | Event |
|---|---|
| 2026-02-22 | Initial build via Antfarm `feature-dev` workflow (run #31). 12 stories, ~2.5h wall-clock. All stories completed autonomously overnight. |
| 2026-02-23 | First data scrape completed. 87 price records, 53 products, 6 snapshots across 5 competitors. |
| 2026-02-23 | Bug-fix run #32 started: Trustpilot parser, Google Reviews, pricing noise. |
| 2026-02-23 | Pushed to GitHub: github.com/MartinPetrov8/competitor_intelligence |

---

## Running Tests

```bash
source venv/bin/activate
PYTHONPATH=. pytest tests/ -v
```

145 tests as of initial build. All pass on main.

---

## Environment Variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `DASHBOARD_PORT` | No | 3001 | Flask dashboard port |
| `DASHBOARD_PASSWORD` | Yes | — | Login password for dashboard |
| `SECRET_KEY` | Yes | — | Flask session signing key |
| `DB_PATH` | No | `./competitor_data.db` | SQLite database path |
| `USER_AGENT` | No | Mozilla/5.0... | HTTP User-Agent for scrapers |
| `REQUEST_TIMEOUT` | No | 30 | Scraper request timeout (seconds) |
| `REQUEST_DELAY` | No | 2 | Delay between requests (seconds) |
