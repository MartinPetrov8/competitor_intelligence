# Sentiment Scraper Implementation Notes

## Status: Needs Browser Automation

The `reviews_sentiment.py` scraper has been created but requires browser automation (Playwright/Selenium) to work properly because:

1. **Trustpilot uses JavaScript rendering** - Reviews are loaded dynamically and don't appear in raw HTML
2. **Star filtering requires interaction** - The `?stars=X` URL parameter needs JavaScript to apply the filter
3. **Dynamic content** - Review cards are rendered client-side

## Current Implementation

The scraper skeleton is in place with:
- ✅ Database schema (`reviews_sentiment` table)
- ✅ Ollama integration for theme extraction
- ✅ Integration with `run_daily.py`
- ❌ Working HTML parsing (blocked by JS requirement)

## Next Steps

### Option 1: Add Playwright (Recommended)

```bash
# Install playwright
pip install playwright
playwright install chromium

# Update requirements.txt
echo "playwright" >> requirements.txt
```

Then modify `reviews_sentiment.py` to use:
```python
from playwright.sync_api import sync_playwright

def _fetch_with_browser(url: str) -> str | None:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(url)
        page.wait_for_selector('article[data-service-review-card-paper]')
        html = page.content()
        browser.close()
        return html
```

### Option 2: Use Trustpilot API (If Available)

Check if Trustpilot offers an API endpoint for fetching reviews by star filter.

### Option 3: Alternative Review Source

If Trustpilot proves too difficult to scrape:
- Google Reviews (via Google My Business API)
- Direct customer feedback forms
- Manual review analysis for pilot

## Testing

Once browser automation is added, test with:
```bash
cd /home/node/.openclaw/workspace/projects/competitor-tracker
.venv/bin/python -m scrapers.reviews_sentiment --db-path competitor_data.db
```

Expected output:
- Extracts 10-50 reviews per star level (1, 2, 3) per competitor
- Runs Ollama theme extraction
- Stores results in `reviews_sentiment` table

## Dashboard Integration

Once data is in the database, the dashboard needs:
1. Query for `reviews_sentiment` table
2. Display "Pain Points" section grouped by `stars_filter`
3. Show theme names, mention counts, and sample quotes

Example query:
```sql
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

## Martin's Original Request

> Update: also scrape `?stars=3` in addition to stars=1 and stars=2. Store all three in `reviews_sentiment` with `stars_filter` = 1, 2, or 3. Include 3-star reviews in the Ollama theme extraction (combine 1+2+3 star texts together for analysis, or run separately and label by star level — your call on what gives cleaner output). Make sure the dashboard Pain Points section reflects this broader set.

✅ Schema supports 1, 2, 3 star filters
✅ Ollama extraction runs per-star-level (cleaner output, easier to see patterns per rating)
❌ Actual scraping blocked by JS requirement
