# Competitor Intelligence Tracker — v2 Architecture

**Project:** DummyVisaTicket Competitor Intelligence Dashboard  
**Location:** `/home/node/.openclaw/workspace/projects/competitor-tracker`  
**GitHub:** https://github.com/MartinPetrov8/competitor_intelligence  
**Deployment:** Render.com (https://competitor-intelligence-pxin.onrender.com)  
**Architect:** Agent (feature-dev_planner)  
**Date:** 2026-02-24  

---

## Executive Summary

This document defines the complete technical architecture for the v2 rebuild of the competitor intelligence tracker. The rebuild addresses critical data quality issues in v1 (duplicate rows, JS noise, unreadable diffs) by implementing structured extraction, deduplication, and intelligent change categorization.

**Core changes from v1:**
- Structured data extraction (no raw HTML dumps)
- One row per competitor per day (UNIQUE constraints)
- Clean separation of main prices vs add-ons
- Boolean product matrix (no free-text descriptions)
- Categorized diff analysis (price/product/copy/layout)
- Improved dashboard UX with trend charts

---

## Technology Stack

### Backend
- **Language:** Python 3.11+
- **Web Framework:** Flask 3.0+ (lightweight, sufficient for read-only dashboard)
- **Database:** SQLite 3 (file-based, simple deployment, adequate for <1M rows)
- **HTTP Client:** requests 2.32+ with User-Agent rotation
- **HTML Parser:** BeautifulSoup 4.12+ with lxml backend
- **Testing:** pytest 8.0+ (145 tests currently passing)
- **Type Checking:** mypy 1.10+ (strict mode)

### Frontend
- **Framework:** Vanilla JavaScript (no build step, CDN dependencies)
- **Charts:** Chart.js 4.x (via CDN)
- **Styling:** Custom CSS with CSS Grid/Flexbox (no framework)
- **State Management:** Plain JS with localStorage for filters

### Deployment
- **Platform:** Render.com free tier
- **Runtime:** Python 3.11 buildpack
- **Auto-deploy:** Push to `main` branch triggers deployment
- **Port:** 10000 (Render default)
- **Authentication:** Session-based password protection (Flask sessions)

### Cron/Scheduling
- **Daily scrapes:** OpenClaw cron (06:00 UTC daily)
- **Scraper runner:** `run_daily.py` (sequential execution)
- **Logging:** Daily log files in `/logs/` directory

---

## Database Architecture

### Schema Design Principles
1. **One row per competitor per day** — UNIQUE constraints on (competitor_id, scrape_date)
2. **v2 suffix during transition** — new tables named `*_v2` until validated
3. **JSON for structured arrays** — add-ons stored as JSON, not separate rows
4. **Explicit type flags** — boolean columns (INTEGER 0/1 in SQLite) for products
5. **Foreign key integrity** — all scraper tables reference `competitors.id`
6. **Indexes on query patterns** — composite indexes on (competitor_id, scrape_date)

### Core Tables (existing, unchanged)
```sql
competitors (id, domain, base_url, created_at)
```

### New Tables (v2)

#### prices_v2
**Purpose:** One clean price row per competitor per day, no JS noise, no duplicates.

```sql
CREATE TABLE prices_v2 (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    competitor_id INTEGER NOT NULL,
    scrape_date TEXT NOT NULL,           -- ISO date: YYYY-MM-DD
    scraped_at TEXT NOT NULL,            -- ISO timestamp with UTC
    main_price REAL,                     -- Primary advertised price (USD equivalent)
    currency TEXT NOT NULL DEFAULT 'USD',
    addons TEXT,                         -- JSON array: [{"name": "Round trip", "price": 7.0}, ...]
    source_url TEXT,                     -- Page where price was found
    UNIQUE(competitor_id, scrape_date),
    FOREIGN KEY (competitor_id) REFERENCES competitors(id)
);
CREATE INDEX idx_prices_v2_competitor_date ON prices_v2 (competitor_id, scrape_date);
```

**Deduplication strategy:**
- INSERT OR REPLACE on UNIQUE constraint
- If same price found on multiple pages (homepage + /pricing), keep first (homepage priority)
- If multiple prices on same page, keep smallest (base price, not upsell)

**Add-ons storage:**
```json
[
  {"name": "Round trip", "price": 7.0},
  {"name": "Extended validity (7 days)", "price": 10.0},
  {"name": "Delayed delivery", "price": 1.0}
]
```

#### products_v2
**Purpose:** Boolean matrix of 4 fixed product categories per competitor.

```sql
CREATE TABLE products_v2 (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    competitor_id INTEGER NOT NULL,
    scrape_date TEXT NOT NULL,
    scraped_at TEXT NOT NULL,
    one_way_offered INTEGER NOT NULL DEFAULT 0,      -- Boolean: 0 or 1
    one_way_price REAL,
    round_trip_offered INTEGER NOT NULL DEFAULT 0,
    round_trip_price REAL,
    hotel_offered INTEGER NOT NULL DEFAULT 0,
    hotel_price REAL,
    visa_letter_offered INTEGER NOT NULL DEFAULT 0,
    visa_letter_price REAL,
    source_url TEXT,
    UNIQUE(competitor_id, scrape_date),
    FOREIGN KEY (competitor_id) REFERENCES competitors(id)
);
CREATE INDEX idx_products_v2_competitor_date ON products_v2 (competitor_id, scrape_date);
```

**Category detection keywords:**
- **One-way:** "one-way", "one way", "onward ticket", "dummy ticket", "flight reservation"
- **Round-trip:** "round trip", "round-trip", "return", "two-way", "two way"
- **Hotel:** "hotel", "accommodation", "hostel"
- **Visa letter:** "visa", "support letter", "invitation letter"

**Price extraction:** Search for `[$€£]\d+` within 200 chars of keyword occurrence.

#### Existing Tables (keep as-is)
```sql
reviews_trustpilot (id, competitor_id, scrape_date, overall_rating, total_reviews, ...)
reviews_google (id, competitor_id, scrape_date, overall_rating, total_reviews, ...)
snapshots (id, competitor_id, scrape_date, page_url, html_content, content_hash)
diffs (id, competitor_id, diff_date, diff_text, additions_count, removals_count)
```

#### Diffs Table Enhancement (NEW)
Add categorization columns to existing `diffs` table:

```sql
ALTER TABLE diffs ADD COLUMN change_categories TEXT;  -- JSON array: ["price_change", "copy_change"]
ALTER TABLE diffs ADD COLUMN change_summary TEXT;     -- Human-readable: "Price updated ($16 → $18)"
```

---

## Scraping Architecture

### Request Management
- **User-Agent rotation:** Cycle through 3 realistic browser UA strings
- **Request delay:** 2-3 seconds between requests (avoid rate limiting)
- **Timeout:** 30 seconds per request
- **Error handling:** Log warning and continue (don't abort full scrape on single failure)

### Scraper Pattern (all scrapers follow this)
```python
1. Connect to DB
2. Ensure table schema exists
3. Get list of competitors
4. For each competitor:
    a. Fetch homepage
    b. Fetch additional paths if needed (/pricing, /products)
    c. Parse HTML (BeautifulSoup or __NEXT_DATA__ JSON)
    d. Extract structured data
    e. Validate/clean data
    f. INSERT OR REPLACE into DB (deduplication via UNIQUE constraint)
    g. Log result
5. Return success/failure flag
```

### Pricing Scraper (`scrapers/pricing.py`)
**Status:** ✅ Complete and working  
**Approach:**
1. Try homepage first (`base_url`)
2. If no price found, try `/pricing`, `/prices`, `/onward-ticket`, `/product`
3. For Next.js sites (onwardticket.com, vizafly.com):
   - Parse `<script id="__NEXT_DATA__">` JSON
   - Extract all prices from JSON blob
   - Main price = smallest price (base offering)
   - Larger prices = add-ons (delta from main)
4. For regular HTML sites:
   - Extract all text nodes containing price patterns `[$€£]\d+`
   - Filter out JS noise (indicators: `__next_f`, `self.__next_f`, `jQuery(`, `<![CDATA[`)
   - Skip any text > 300 chars (likely JS code, not copy)
   - Main price = smallest price in clean text
   - Detect add-ons via patterns like "Round Trip (+$7)"
5. Store ONE row per competitor per day

### Products Scraper (`scrapers/products.py`)
**Status:** ✅ Complete and working  
**Approach:**
1. Fetch homepage, `/products`, `/services`, `/pricing`, `/onward-ticket`
2. For each page, extract lowercased plain text
3. For each of 4 categories, check if ANY keyword is present in text
4. If category keyword found, search nearby text (±200 chars) for price pattern
5. Merge results across all pages (OR-combine booleans, first price wins)
6. Store ONE row per competitor per day

### Reviews Scraper — Trustpilot (`scrapers/reviews_trustpilot.py`)
**Status:** ✅ Working (no changes needed)  
**Approach:**
1. Construct Trustpilot URL: `https://www.trustpilot.com/review/{domain}`
2. Fetch page and parse `<script id="__NEXT_DATA__">`
3. Extract `trustScore` (1.0–5.0) and `numberOfReviews`
4. Store in `reviews_trustpilot` table

### Reviews Scraper — Google (`scrapers/reviews_google.py`)
**Status:** ❌ Currently broken, needs fix  
**Problem:** Google Knowledge Panel parsing is inconsistent  
**Approach to fix:**
1. Search URL: `https://www.google.com/search?q={domain}+reviews`
2. Parse HTML for Knowledge Panel div (`<div class="gsrt">` or similar)
3. Extract star rating (e.g., "4.2" from "4.2 out of 5 stars")
4. Extract review count (e.g., "124 reviews")
5. Use robust selectors (test against multiple competitors)
6. If not found, store NULL (acceptable — not all sites have Google reviews)

**Acceptance criteria:**
- At least 1 out of 5 competitors must return a non-NULL rating
- No crash on missing data

### Snapshots Scraper (`scrapers/snapshots.py`)
**Status:** ✅ Working (keep as-is)  
**Approach:**
1. Fetch homepage HTML
2. Store full HTML in `snapshots` table with content hash
3. Compute diff vs previous day's snapshot (using Python difflib)
4. Store diff in `diffs` table

**NEW requirement:** Add change categorization after diff computation.

### Change Categorization (NEW feature)
**Where:** Add logic to `scrapers/snapshots.py` after diff computation  
**Input:** Raw diff text (additions + removals)  
**Output:** JSON array of category labels + human-readable summary

**Categories:**
- `price_change` — diff contains price patterns that changed (`$\d+`, `€\d+`, `£\d+`)
- `product_change` — diff mentions product keywords (ticket, hotel, visa, onward, return, booking)
- `copy_change` — text content changed (headlines, descriptions, CTAs)
- `layout_change` — structural HTML changes (`<div`, `<section`, `<nav`, `class=`)

**Classification rules (regex-based):**
```python
import re

def categorize_diff(diff_text: str) -> tuple[list[str], str]:
    """
    Return (categories, summary).
    Example: (["price_change", "copy_change"], "Price updated ($16 → $18), hero text changed")
    """
    categories = []
    
    # Price change: look for price pattern in diff
    if re.search(r'[$€£]\d+', diff_text):
        categories.append("price_change")
    
    # Product change: product-related keywords
    product_keywords = ["ticket", "hotel", "visa", "onward", "return", "booking", "reservation"]
    if any(kw in diff_text.lower() for kw in product_keywords):
        categories.append("product_change")
    
    # Layout change: HTML structure keywords
    layout_keywords = ["<div", "<section", "<nav", "class=", "<header", "<footer"]
    if any(kw in diff_text for kw in layout_keywords):
        categories.append("layout_change")
    
    # Copy change: if diff exists but not price/product/layout, assume copy
    if not categories and len(diff_text.strip()) > 0:
        categories.append("copy_change")
    
    # Generate summary (simple heuristic)
    summary_parts = []
    if "price_change" in categories:
        summary_parts.append("Price text changed")
    if "product_change" in categories:
        summary_parts.append("Product info updated")
    if "copy_change" in categories:
        summary_parts.append("Text content changed")
    if "layout_change" in categories:
        summary_parts.append("Layout structure modified")
    
    summary = ", ".join(summary_parts) if summary_parts else "Minor changes"
    
    return categories, summary
```

**Storage:**
```python
# After computing diff in scrapers/snapshots.py
categories, summary = categorize_diff(diff_text)
categories_json = json.dumps(categories)

conn.execute(
    """
    INSERT INTO diffs (competitor_id, diff_date, diff_text, change_categories, change_summary, ...)
    VALUES (?, ?, ?, ?, ?, ...)
    """,
    (competitor_id, diff_date, diff_text, categories_json, summary, ...)
)
```

### AB Testing Scraper (`scrapers/ab_tests.py`)
**Status:** ✅ Working (keep as-is)  
**No changes needed.**

---

## Dashboard Architecture

### Backend (Flask)
**File:** `dashboard/server.py`

#### API Endpoints (RESTful)
```
GET  /api/competitors              → List all competitors
GET  /api/prices                   → Prices data (with filters)
GET  /api/products                 → Products data (with filters)
GET  /api/reviews                  → Reviews data (Trustpilot + Google combined)
GET  /api/site-changes             → Site changes with categories
GET  /api/health                   → Health check (public, no auth)

GET  /                             → Dashboard HTML (protected)
GET  /login                        → Login page
POST /login                        → Login form submission
GET  /logout                       → Logout
```

#### Authentication
- **Strategy:** Session-based with Flask sessions
- **Password:** Environment variable `DASHBOARD_PASSWORD` (default: "changeme")
- **Session key:** `authenticated = True/False`
- **Public routes:** `/login`, `/health` (skip auth)
- **Protected routes:** All others (redirect to /login if not authenticated)

#### Query Filters (all API endpoints)
```
?competitor=domain.com     → Filter by competitor
?date=YYYY-MM-DD           → Filter by specific date
?start_date=YYYY-MM-DD     → Filter by date range start
?end_date=YYYY-MM-DD       → Filter by date range end
```

#### Response Format
All API endpoints return JSON:
```json
{
  "data": [...],           // Array of records
  "count": 123,            // Total count
  "filters": {             // Applied filters (for debugging)
    "competitor": "onwardticket.com",
    "date": "2026-02-23"
  }
}
```

### Frontend (Vanilla JS)
**File:** `dashboard/static/index.html`

#### Tab Structure
```html
<div class="tab-bar">
  <button class="tab-btn active" data-tab="pricing">💰 Pricing</button>
  <button class="tab-btn" data-tab="products">📦 Products</button>
  <button class="tab-btn" data-tab="reviews">⭐ Reviews</button>
  <button class="tab-btn" data-tab="site-changes">📝 Site Changes</button>
</div>

<div id="pricing" class="tab-content active">...</div>
<div id="products" class="tab-content hidden">...</div>
<div id="reviews" class="tab-content hidden">...</div>
<div id="site-changes" class="tab-content hidden">...</div>
```

#### Tab 1: Pricing
**Display:**
- Table: one row per competitor
- Columns: `Competitor | Main Price | Currency | Add-ons | Last Updated`
- Price change indicator: 🔻 green (cheaper) or 🔺 red (more expensive) vs yesterday
- Add-ons: collapsed by default, click to expand (accordion)
- Line chart: main_price over time per competitor (Chart.js)

**Data fetch:**
```javascript
fetch('/api/prices?start_date=2026-01-01')
  .then(r => r.json())
  .then(data => {
    renderPricingTable(data.data);
    renderPricingChart(data.data);
  });
```

**Add-ons rendering:**
```javascript
function renderAddons(addonsJson) {
  if (!addonsJson) return 'None';
  const addons = JSON.parse(addonsJson);
  const html = addons.map(a => `<li>${a.name}: $${a.price.toFixed(2)}</li>`).join('');
  return `<ul class="addons-list">${html}</ul>`;
}
```

#### Tab 2: Products
**Display:**
- Comparison matrix: rows = competitors, columns = 4 product categories
- Cell format: `✅ $16` (offered with price) or `❌` (not offered)
- No free text, no descriptions

**Data fetch:**
```javascript
fetch('/api/products?date=2026-02-23')
  .then(r => r.json())
  .then(data => renderProductsMatrix(data.data));
```

**Matrix HTML:**
```html
<table>
  <thead>
    <tr>
      <th>Competitor</th>
      <th>One-way Ticket</th>
      <th>Round-trip</th>
      <th>Hotel Booking</th>
      <th>Visa Letter</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td>onwardticket.com</td>
      <td>✅ $16</td>
      <td>✅ $23</td>
      <td>❌</td>
      <td>❌</td>
    </tr>
    ...
  </tbody>
</table>
```

#### Tab 3: Reviews
**Display:**
- Table: one row per competitor
- Columns: `Competitor | Trustpilot ⭐ | TP Reviews | Google ⭐ | G Reviews | Last Updated`
- Show "N/A" for missing data (e.g., vizafly not on Trustpilot)
- Trend chart: rating over time per competitor (Chart.js)

**Data fetch:**
```javascript
fetch('/api/reviews')
  .then(r => r.json())
  .then(data => {
    renderReviewsTable(data.data);
    renderReviewsChart(data.data);
  });
```

#### Tab 4: Site Changes
**Display:**
- Only show competitors with changes vs previous day
- If no changes: display "✅ No changes detected today"
- Per changed competitor:
  - Date
  - List of change categories with emoji icons:
    - 💰 Price change
    - 📦 Product change
    - 📝 Copy change
    - 🎨 Layout change
  - Brief description (from `change_summary` column)
  - Optional: "View raw diff" expand button (for technical users)

**Example:**
```
dummy-tickets.com — 2026-02-23
  💰 Price change: Price text changed
  📝 Copy change: Text content changed

onwardticket.com — 2026-02-23
  🎨 Layout change: Layout structure modified
```

**Data fetch:**
```javascript
fetch('/api/site-changes?date=2026-02-23')
  .then(r => r.json())
  .then(data => renderSiteChanges(data.data));
```

#### Responsive Design
- Desktop: full table layout
- Tablet: horizontal scroll for tables
- Mobile: card-based layout (stack columns vertically)
- Breakpoints: 768px (tablet), 480px (mobile)

#### State Management
- Filter selections stored in localStorage
- On page load, restore previous filter selections
- No backend state (stateless API)

---

## Testing Strategy

### Test Coverage Requirements
- **Unit tests:** All scraper extraction functions (pricing, products, reviews)
- **Integration tests:** Full scrape runs with mocked HTTP responses
- **Schema tests:** Table structure validation, UNIQUE constraints
- **Dashboard tests:** API endpoints (with/without auth), response formats
- **Regression tests:** Ensure existing 145 tests continue to pass

### Test Organization
```
tests/
├── test_pricing_v2.py          # Pricing scraper unit tests
├── test_products_v2.py         # Products scraper unit tests
├── test_reviews_google.py      # Google reviews scraper (fix existing)
├── test_schema_v2.py           # Database schema validation
├── test_dashboard_server.py    # API endpoint tests
├── test_auth.py                # Authentication tests
└── test_integration.py         # End-to-end scrape tests
```

### Running Tests
```bash
source venv/bin/activate
PYTHONPATH=. pytest tests/ -x -q          # Stop on first failure
PYTHONPATH=. pytest tests/ -v             # Verbose output
PYTHONPATH=. pytest tests/test_pricing_v2.py  # Single file
```

### Acceptance Criteria (Binary Pass/Fail)
1. `prices_v2` table: exactly ONE row per competitor per scrape_date, main_price populated, no JS noise ✅
2. `products_v2` table: exactly ONE row per competitor per scrape_date, boolean flags correctly set ✅
3. Trustpilot reviews: still working (regression test) ✅
4. Google reviews: at least 1 competitor returns a rating ❌ (needs fix)
5. Site changes tab: shows categorized changes, hides competitors with no changes ❌ (needs implementation)
6. Pricing tab: shows one row per competitor, add-ons collapsible ❌ (needs frontend update)
7. Products tab: matrix with ✅/❌ per category per competitor ❌ (needs frontend update)
8. All existing tests pass + new tests added ❌ (in progress)

---

## Deployment

### Render.com Configuration
**File:** `render.yaml`

```yaml
services:
  - type: web
    name: competitor-intelligence
    runtime: python
    buildCommand: pip install -r requirements.txt
    startCommand: PYTHONPATH=. python3 dashboard/server.py
    envVars:
      - key: DASHBOARD_PORT
        value: 10000                    # Render default
      - key: DASHBOARD_PASSWORD
        sync: false                     # Manual secret management
      - key: SECRET_KEY
        generateValue: true             # Flask session secret
      - key: DB_PATH
        value: ./competitor_data.db
      - key: PYTHON_VERSION
        value: 3.11.0
```

### Deployment Process
1. Push to `main` branch → triggers auto-deploy
2. Render runs `pip install -r requirements.txt`
3. Render starts `PYTHONPATH=. python3 dashboard/server.py`
4. Dashboard available at https://competitor-intelligence-pxin.onrender.com
5. Password: `dummyvisa2026` (environment variable, not in repo)

### Database Persistence
- SQLite file (`competitor_data.db`) is ephemeral on Render free tier
- DB resets on redeploy or dyno restart
- **Solution:** Daily scrapes run via OpenClaw cron, not Render
- Render dashboard is read-only view of data
- Production DB lives on OpenClaw host, not Render

---

## Cron Configuration

### OpenClaw Cron Job
**Schedule:** Daily at 06:00 UTC  
**Command:**
```bash
cd /home/node/.openclaw/workspace/projects/competitor-tracker && \
source venv/bin/activate && \
PYTHONPATH=. python3 run_daily.py
```

**Logging:**
- Daily log files: `/logs/daily_YYYY-MM-DD.log`
- Log rotation: keep last 30 days
- Log format: `%(asctime)s [%(levelname)s] %(message)s`

**Error Handling:**
- Individual scraper failures don't abort full run
- Each scraper logs status: `success`, `no_data`, or `failed`
- Summary printed at end: `name,status,rows_inserted,duration_seconds`

---

## Migration Plan (v1 → v2)

### Phase 1: Parallel Tables
1. Keep existing tables (`prices`, `products`, etc.)
2. Create new tables with `_v2` suffix
3. Run both scrapers in parallel (write to both v1 and v2 tables)
4. Validate v2 data quality for 1 week

### Phase 2: Dashboard Update
1. Update API endpoints to read from `_v2` tables
2. Update frontend to match new data structure
3. Deploy to Render
4. User acceptance testing

### Phase 3: Cleanup
1. Drop v1 tables: `DROP TABLE prices; DROP TABLE products;`
2. Rename v2 tables: `ALTER TABLE prices_v2 RENAME TO prices;`
3. Update scraper code to remove `_v2` suffix
4. Final deployment

---

## File Manifest

### Files to Modify
```
database/schema.py                # Add _v2 table definitions
scrapers/pricing.py               # ✅ Already done
scrapers/products.py              # ✅ Already done
scrapers/reviews_google.py        # ❌ Fix parsing
scrapers/snapshots.py             # ❌ Add categorization
dashboard/server.py               # ❌ Update API endpoints for v2
dashboard/static/index.html       # ❌ Full frontend redesign
tests/test_reviews_google.py      # ❌ Fix/expand tests
tests/test_schema_v2.py           # ✅ Already done
init_db.py                        # ✅ Already updated (has v2 tables)
```

### Files to Keep (No Changes)
```
scrapers/reviews_trustpilot.py    # ✅ Working
scrapers/ab_tests.py              # ✅ Working
scrapers/__init__.py
dashboard/__init__.py
dashboard/templates/login.html    # ✅ Working
run_daily.py                      # ✅ Working
render.yaml                       # ✅ Working
requirements.txt                  # ✅ Complete
.gitignore                        # ✅ Complete
```

---

## Risk Assessment

### High Risk
- **Google Reviews scraper:** Depends on unstable HTML structure (Google changes selectors frequently)
  - **Mitigation:** Accept NULL values gracefully, test against multiple sites, use multiple selector strategies

### Medium Risk
- **Dashboard frontend redesign:** Complex JS state management for filters/charts
  - **Mitigation:** Keep state management simple (localStorage only), use vanilla JS (no framework lock-in)

- **Diff categorization accuracy:** Regex-based classification may have false positives
  - **Mitigation:** Categories are informational only (not critical), user can view raw diff

### Low Risk
- **SQLite performance:** May slow down with >1M rows
  - **Mitigation:** Current scale is ~5 competitors × 365 days × 5 tables = ~10K rows/year (acceptable)

- **Render deployment:** Free tier has cold starts, database resets
  - **Mitigation:** Dashboard is read-only view, primary DB on OpenClaw host

---

## Success Metrics

### Data Quality
- Zero duplicate rows per (competitor, date) pair
- Zero rows with JS noise in `main_price`
- 100% of scraped pages yield ONE clean price row
- 100% of products categorized into 4 fixed categories

### User Experience
- Dashboard loads in <2 seconds
- Price trend charts render correctly for all competitors
- Site changes tab shows only relevant changes (signal-to-noise ratio)

### System Health
- Daily scrapes complete in <5 minutes
- 100% scraper uptime (graceful error handling, no crashes)
- All 145+ tests pass on every commit

---

## Glossary

- **Main price:** The primary advertised price for a single one-way dummy ticket
- **Add-on:** Optional extra with additional cost (round trip, extended validity, etc.)
- **Deduplication:** Ensuring only ONE row exists per (competitor, date) pair
- **JS noise:** JavaScript code accidentally extracted as price text (e.g., `__next_f`, `jQuery`)
- **Categorization:** Classifying diffs into price/product/copy/layout categories
- **Knowledge Panel:** Google's info box on search results (contains ratings)

---

## Appendix A: Competitor URLs

| Competitor | Homepage | Trustpilot | Notes |
|---|---|---|---|
| onwardticket.com | https://onwardticket.com | https://www.trustpilot.com/review/onwardticket.com | Next.js site, parse `__NEXT_DATA__` |
| bestonwardticket.com | https://bestonwardticket.com | https://www.trustpilot.com/review/bestonwardticket.com | Regular HTML |
| dummyticket.com | https://dummyticket.com | https://www.trustpilot.com/review/dummyticket.com | Regular HTML |
| dummy-tickets.com | https://dummy-tickets.com | https://www.trustpilot.com/review/dummy-tickets.com | Regular HTML |
| vizafly.com | https://vizafly.com | N/A (not on Trustpilot) | Next.js site |

---

## Appendix B: Example API Responses

### GET /api/prices
```json
{
  "data": [
    {
      "competitor": "onwardticket.com",
      "scrape_date": "2026-02-23",
      "main_price": 16.0,
      "currency": "USD",
      "addons": "[{\"name\": \"Round trip\", \"price\": 7.0}]",
      "source_url": "https://onwardticket.com"
    }
  ],
  "count": 1,
  "filters": {"date": "2026-02-23"}
}
```

### GET /api/products
```json
{
  "data": [
    {
      "competitor": "onwardticket.com",
      "scrape_date": "2026-02-23",
      "one_way_offered": 1,
      "one_way_price": 16.0,
      "round_trip_offered": 1,
      "round_trip_price": 23.0,
      "hotel_offered": 0,
      "hotel_price": null,
      "visa_letter_offered": 0,
      "visa_letter_price": null
    }
  ],
  "count": 1
}
```

### GET /api/site-changes
```json
{
  "data": [
    {
      "competitor": "dummy-tickets.com",
      "diff_date": "2026-02-23",
      "change_categories": "[\"price_change\", \"copy_change\"]",
      "change_summary": "Price text changed, Text content changed",
      "additions_count": 15,
      "removals_count": 12
    }
  ],
  "count": 1
}
```

---

## Appendix C: Chart.js Configuration

### Price Trend Chart
```javascript
const ctx = document.getElementById('price-chart').getContext('2d');
new Chart(ctx, {
  type: 'line',
  data: {
    labels: ['2026-02-20', '2026-02-21', '2026-02-22', '2026-02-23'],  // dates
    datasets: [
      {
        label: 'onwardticket.com',
        data: [16, 16, 16, 18],
        borderColor: '#2563eb',
        backgroundColor: 'rgba(37, 99, 235, 0.1)'
      },
      {
        label: 'bestonwardticket.com',
        data: [14, 14, 14, 14],
        borderColor: '#dc2626',
        backgroundColor: 'rgba(220, 38, 38, 0.1)'
      }
    ]
  },
  options: {
    responsive: true,
    plugins: {
      legend: { position: 'bottom' },
      title: { display: true, text: 'Price Trends (Last 30 Days)' }
    },
    scales: {
      y: { beginAtZero: false, ticks: { callback: v => `$${v}` } }
    }
  }
});
```

---

**End of Architecture Document**
