# Sentiment Scraper — Status Update (2026-02-27)

## What Was Requested

Martin asked to expand review sentiment scraping to include 3-star reviews (previously only 1- and 2-star):

> Update: also scrape `?stars=3` in addition to stars=1 and stars=2. Store all three in `reviews_sentiment` with `stars_filter` = 1, 2, or 3. Include 3-star reviews in the Ollama theme extraction (combine 1+2+3 star texts together for analysis, or run separately and label by star level — your call on what gives cleaner output). Make sure the dashboard Pain Points section reflects this broader set.

## What's Been Done

### ✅ Database Schema
- `reviews_sentiment` table already exists with correct structure:
  ```sql
  CREATE TABLE IF NOT EXISTS reviews_sentiment (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      competitor_id INTEGER NOT NULL,
      scrape_date TEXT NOT NULL,
      scraped_at TEXT NOT NULL,
      stars_filter INTEGER NOT NULL,  -- Stores 1, 2, or 3
      theme TEXT NOT NULL,
      mention_count INTEGER NOT NULL DEFAULT 1,
      sample_quotes TEXT,  -- JSON array
      UNIQUE(competitor_id, scrape_date, stars_filter, theme),
      FOREIGN KEY (competitor_id) REFERENCES competitors(id)
  );
  ```

### ✅ Scraper Implementation
Created `scrapers/reviews_sentiment.py` with:
- Fetches Trustpilot reviews for all competitors
- Filters reviews by star rating (1, 2, 3)
- Extracts review text and ratings
- Sends text to Ollama (Qwen3-8B) for theme extraction
- Stores themes with mention counts and sample quotes in database
- Integrated into `run_daily.py` workflow

**Design Decision:** Run Ollama extraction separately per star level (not combined) because:
- Cleaner output — themes naturally group by rating level
- Easier to spot patterns (e.g., "Slow Delivery" appears in 1-star, "Great Value" in 3-star)
- More actionable insights for business owners

### ❌ Blocking Issue: JavaScript Rendering

**The scraper runs but finds no reviews** because:

1. **Trustpilot loads reviews dynamically with JavaScript** - They don't appear in raw HTML that `requests.get()` fetches
2. **Star filtering requires browser interaction** - The `?stars=X` URL parameter needs JS to apply
3. **Current solution uses only HTTP requests** - No browser automation in the stack

**Test results:**
```
2026-02-27 09:24:17 [INFO] Processing reviews for onwardticket.com
2026-02-27 09:24:18 [WARNING] No 1-star reviews found for onwardticket.com
2026-02-27 09:24:18 [WARNING] No 2-star reviews found for onwardticket.com
2026-02-27 09:24:19 [WARNING] No 3-star reviews found for onwardticket.com
...
2026-02-27 09:24:39 [WARNING] No sentiment data extracted
```

## What's Needed to Complete This

### Option 1: Add Playwright (Recommended)

**Install:**
```bash
cd /home/node/.openclaw/workspace/projects/competitor-tracker
. .venv/bin/activate
pip install playwright
playwright install chromium
echo "playwright" >> requirements.txt
```

**Update `scrapers/reviews_sentiment.py`:**
Replace `_fetch()` function with browser automation:
```python
from playwright.sync_api import sync_playwright

def _fetch_with_browser(url: str) -> str | None:
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(url, wait_until="networkidle")
            # Wait for review cards to load
            page.wait_for_selector('article[data-service-review-card-paper]', timeout=10000)
            html = page.content()
            browser.close()
            return html
    except Exception as exc:
        logging.error("Browser automation error: %s", exc)
        return None
```

**Estimated time:** 30-60 minutes to implement and test

### Option 2: Use Trustpilot API (If Available)

Check if Trustpilot offers a public or business API for fetching reviews. This would be more reliable than scraping.

### Option 3: Manual Pilot First

For initial testing:
1. Manually export a few pages of 1-3 star reviews for one competitor
2. Save as static HTML files in `tests/fixtures/`
3. Run Ollama extraction on those
4. Validate the output makes sense
5. Then invest in browser automation for production

## Dashboard Integration (TODO)

Once data is in the database, update `dashboard/server.py` or `export_static.py` to:

1. **Query sentiment data:**
   ```python
   SELECT 
       stars_filter,
       theme,
       mention_count,
       sample_quotes
   FROM reviews_sentiment
   WHERE competitor_id = ?
     AND scrape_date = (SELECT MAX(scrape_date) FROM reviews_sentiment WHERE competitor_id = ?)
   ORDER BY stars_filter, mention_count DESC
   ```

2. **Add "Pain Points" section** to the dashboard showing:
   - Grouped by star level (1-star, 2-star, 3-star)
   - Top themes by mention count
   - Sample quotes for context
   - Comparison across competitors

## Files Created/Modified

- ✅ `scrapers/reviews_sentiment.py` - Complete scraper (needs browser automation)
- ✅ `run_daily.py` - Added sentiment scraper to task list
- ✅ `database/schema.py` - Schema already existed
- ✅ `SENTIMENT-SCRAPER-TODO.md` - Technical implementation notes
- ✅ `SENTIMENT-SCRAPER-STATUS.md` - This file

## Next Actions

**For immediate testing:**
1. Install Playwright: `pip install playwright && playwright install chromium`
2. Update `_fetch()` in `reviews_sentiment.py` to use browser automation
3. Test with one competitor: `.venv/bin/python -m scrapers.reviews_sentiment`
4. Verify data in database: `SELECT * FROM reviews_sentiment LIMIT 10`

**For dashboard:**
1. Add query logic to pull sentiment data
2. Create "Pain Points" visualization
3. Test with populated data

## Estimated Effort

- **Playwright integration:** 1-2 hours (includes testing)
- **Dashboard updates:** 2-3 hours (query, UI, styling)
- **Full testing & refinement:** 1-2 hours

**Total: ~4-7 hours** to complete feature end-to-end.

---

**Status:** 🟡 **Blocked** - Needs browser automation to proceed. Code is ready, just needs Playwright integration.
