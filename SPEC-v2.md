# Competitor Intelligence Tracker — v2 Spec

## Overview
Complete rebuild of scrapers and dashboard for DummyVisaTicket competitor intelligence.
Project location: `/home/node/.openclaw/workspace/projects/competitor-tracker`
GitHub: https://github.com/MartinPetrov8/competitor_intelligence

## Competitors
1. onwardticket.com
2. bestonwardticket.com
3. dummyticket.com
4. dummy-tickets.com
5. vizafly.com

---

## Problem with current v1
The v1 scrapers dump raw HTML/page text into the DB with no deduplication or structured extraction.
Results: hundreds of duplicate rows, JS noise, meaningless product names, unreadable diffs.
This spec defines EXACTLY what to extract and how to display it.

---

## Tab 1: Pricing

### What to scrape
For each competitor, extract:
- **Main price** (the primary price advertised for a single one-way dummy/onward ticket)
- **Add-ons** (any optional extras with their prices, e.g. "Round trip +$7", "Extended validity +$10", "Delayed delivery +$1")

### Scraping rules
- Use requests + BeautifulSoup. For Next.js sites (onwardticket.com, vizafly.com), parse `__NEXT_DATA__` JSON.
- Deduplicate: store ONE main price row per competitor per scrape_date. Store add-ons as separate rows with `is_addon=True`.
- If the same price appears on homepage and pricing page, only store it once.
- Skip any row where `raw_text` contains JS indicators: `self.__next_f`, `<![CDATA[`, `jQuery(`, `gform.`, `__next_f`
- Skip any row where `raw_text` length > 300 chars

### DB schema (replace current prices table)
```sql
CREATE TABLE prices_v2 (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    competitor_id INTEGER NOT NULL,
    scrape_date TEXT NOT NULL,
    scraped_at TEXT NOT NULL,
    main_price REAL,           -- primary advertised price in USD
    currency TEXT DEFAULT 'USD',
    addons TEXT,               -- JSON array: [{"name": "Round trip", "price": 7.0}, ...]
    source_url TEXT,
    UNIQUE(competitor_id, scrape_date)  -- one row per competitor per day
);
```

### Dashboard display
- Table: one row per competitor
- Columns: Competitor | Main Price | Add-ons (collapsed by default, click to expand)
- Price trend chart: line chart showing main_price over time per competitor
- Highlight if price changed vs previous day (green = cheaper, red = more expensive)

---

## Tab 2: Products

### What to scrape
For each competitor, detect whether they offer each of these 4 fixed categories:
1. **One-way ticket** — onward/dummy flight ticket, single direction
2. **Round-trip ticket** — return flight reservation
3. **Hotel booking** — dummy hotel reservation
4. **Visa support letter** — formal letter for visa applications

### Scraping rules
- Scrape homepage + any /products, /services pages
- For each category, set `offered = True/False` based on keyword detection:
  - One-way: "one-way", "onward ticket", "dummy ticket", "flight reservation"
  - Round-trip: "round trip", "return", "two-way"
  - Hotel: "hotel", "accommodation", "hostel"
  - Visa letter: "visa", "support letter", "invitation letter"
- Also capture the price for that product if visible on the page

### DB schema (replace current products table)
```sql
CREATE TABLE products_v2 (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    competitor_id INTEGER NOT NULL,
    scrape_date TEXT NOT NULL,
    scraped_at TEXT NOT NULL,
    one_way_offered BOOLEAN DEFAULT FALSE,
    one_way_price REAL,
    round_trip_offered BOOLEAN DEFAULT FALSE,
    round_trip_price REAL,
    hotel_offered BOOLEAN DEFAULT FALSE,
    hotel_price REAL,
    visa_letter_offered BOOLEAN DEFAULT FALSE,
    visa_letter_price REAL,
    UNIQUE(competitor_id, scrape_date)
);
```

### Dashboard display
- Comparison matrix: rows = competitors, columns = 4 product categories
- Cell shows: ✅ $16 or ❌ (not offered)
- No free-text product names, no descriptions

---

## Tab 3: Reviews

### What to scrape

**Trustpilot** (already working):
- Parse `__NEXT_DATA__` JSON for `trustScore` and `numberOfReviews`
- If competitor not on Trustpilot, store NULL

**Google Reviews** (currently broken — needs fix):
- Search Google for "{domain} reviews" and parse the Knowledge Panel rating
- Use: `https://www.google.com/search?q={domain}+site+reviews`
- Parse the star rating and review count from the search result page
- If not found, store NULL

### DB schema (keep existing, already correct)
```sql
reviews_trustpilot: overall_rating, total_reviews (already working)
reviews_google: overall_rating, total_reviews (needs fix)
```

### Dashboard display
- Table: one row per competitor
- Columns: Competitor | Trustpilot ⭐ | TP Reviews | Google ⭐ | G Reviews | Last Updated
- Trend chart: rating over time per competitor

---

## Tab 4: Site Changes

### What to scrape
- Daily HTML snapshot of homepage per competitor (already working)
- Diff against previous day's snapshot

### Change categorization (NEW — this is the key requirement)
After computing the raw diff, classify each change into one of these categories:
- 💰 **Price change** — diff text contains price patterns ($X, €X, £X) that changed
- 📦 **Product change** — diff text mentions product names or service offerings
- 📝 **Copy change** — text content changed (headlines, descriptions, CTAs)
- 🎨 **Layout change** — structural HTML changes (new sections, removed elements, nav changes)

Use simple keyword/pattern rules to classify. One snapshot diff can have multiple categories.

### Dashboard display
- Only show competitors where something changed vs previous day
- If no changes across any competitor: show "No changes detected today"
- Per changed competitor: show date, list of change categories with brief description
- Example:
  ```
  dummy-tickets.com — Feb 23
    📝 Copy change: Product description updated ("Live PNR" section)
    💰 Price change: Validity text updated ("48 hours to 2 weeks")
  ```
- Optional: "View raw diff" expand button for technical users

---

## Implementation Requirements

### General rules
- All scrapers must handle errors gracefully (timeout, 404, blocked) — log warning and continue
- Request delay: 2-3 seconds between requests to avoid rate limiting
- User-Agent: rotate between 3 realistic browser UA strings
- All new tables use `_v2` suffix during transition; drop old tables after validation
- Deduplication: use UNIQUE constraints + INSERT OR IGNORE or INSERT OR REPLACE
- Run existing 145 tests + add new tests for all new scraper logic
- Use venv: `bash -c "source venv/bin/activate && ..."`
- PYTHONPATH=. for all python commands

### Files to modify
- `scrapers/pricing.py` — full rewrite
- `scrapers/products.py` — full rewrite  
- `scrapers/reviews_google.py` — fix parsing
- `database/schema.py` — add new tables
- `dashboard/server.py` — update API endpoints
- `dashboard/static/` — update frontend for new data structure
- `init_db.py` — run new schema migrations

### Do NOT modify
- `scrapers/reviews_trustpilot.py` — already working
- `scrapers/snapshots.py` — keep as-is
- `scrapers/ab_tests.py` — keep as-is
- Existing test files for working scrapers

### Acceptance criteria (binary pass/fail)
1. `prices_v2` table: exactly ONE row per competitor per scrape_date, main_price populated, no JS noise
2. `products_v2` table: exactly ONE row per competitor per scrape_date, boolean flags correctly set
3. Trustpilot reviews: still working (regression test)
4. Google reviews: at least 1 competitor returns a rating
5. Site changes tab: shows categorized changes, hides competitors with no changes
6. Pricing tab: shows one row per competitor, add-ons collapsible
7. Products tab: matrix with ✅/❌ per category per competitor
8. All 145 existing tests pass + new tests added
