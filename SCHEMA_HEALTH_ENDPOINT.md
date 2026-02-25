# Database Schema for Health Endpoint

This document describes the database schema elements required for the `/health` endpoint.

## Tables Required

### competitors
The `competitors` table stores the list of tracked competitor sites.

**Columns:**
- `id` (INTEGER PRIMARY KEY) - Unique identifier
- `domain` (TEXT NOT NULL UNIQUE) - Competitor domain name
- `base_url` (TEXT NOT NULL) - Base URL for the competitor site
- `created_at` (TEXT) - Timestamp when competitor was added

**Health Endpoint Usage:** COUNT(*) from this table provides the `scrapers` count.

**Example Query:**
```sql
SELECT COUNT(*) FROM competitors;
```

### Scraper Tables with scraped_at

All scraper tables include a `scraped_at` column (TEXT, ISO 8601 datetime format) that records when the data was collected.

**Tables:**
1. `prices_v2` - Pricing data (one row per competitor per day)
2. `products_v2` - Product catalog data (one row per competitor per day)
3. `reviews_trustpilot` - Trustpilot review metrics
4. `reviews_google` - Google review metrics
5. `ab_tests` - A/B testing framework detection
6. `snapshots` - Website snapshots

**Health Endpoint Usage:** MAX(scraped_at) across all tables provides the `last_run` timestamp.

**Example Query:**
```sql
SELECT MAX(scraped_at) AS last_run FROM (
    SELECT MAX(scraped_at) AS scraped_at FROM prices_v2
    UNION ALL
    SELECT MAX(scraped_at) FROM products_v2
    UNION ALL
    SELECT MAX(scraped_at) FROM reviews_trustpilot
    UNION ALL
    SELECT MAX(scraped_at) FROM reviews_google
    UNION ALL
    SELECT MAX(scraped_at) FROM ab_tests
    UNION ALL
    SELECT MAX(scraped_at) FROM snapshots
);
```

## Verification

The schema has been verified to support health endpoint requirements via `tests/test_health_endpoint_schema.py`:
- ✅ competitors table exists and is queryable
- ✅ competitors table has id, domain, base_url columns
- ✅ All 6 scraper tables exist
- ✅ All 6 scraper tables have scraped_at column
- ✅ MAX(scraped_at) can be queried from all tables

## No Schema Changes Required

The existing database schema fully supports the health endpoint requirements. No ALTER TABLE or CREATE TABLE statements are needed.
