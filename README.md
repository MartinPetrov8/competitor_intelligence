# Competitor Intelligence Tracker

A daily automated scraper that captures competitor pricing, product offerings, website changes, and review metrics for [DummyVisaTicket](https://dummyvisaticket.com). Results are displayed on a shared dashboard for morning review.

---

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [Competitors Tracked](#competitors-tracked)
3. [Quick Start](#quick-start)
4. [Configuration](#configuration)
5. [Running the Scrapers](#running-the-scrapers)
6. [Dashboard](#dashboard)
7. [Cron Setup](#cron-setup)
8. [Running Tests](#running-tests)
9. [Project Structure](#project-structure)
10. [Database Schema](#database-schema)
11. [Troubleshooting](#troubleshooting)

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────┐
│                   run_daily.py (cron)                   │
│                                                         │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐  │
│  │ Pricing  │ │ Products │ │Snapshots │ │ Reviews  │  │
│  │ scraper  │ │ scraper  │ │ & Diffs  │ │ scraper  │  │
│  └────┬─────┘ └────┬─────┘ └────┬─────┘ └────┬─────┘  │
│       │             │             │             │        │
│  ┌────▼─────────────▼─────────────▼─────────────▼────┐  │
│  │              SQLite  (competitor_data.db)         │  │
│  └───────────────────────────┬───────────────────────┘  │
│                               │                          │
│               ┌───────────────▼──────────────┐          │
│               │   Flask Dashboard  :3001      │          │
│               │   (with basic auth)           │          │
│               └──────────────────────────────┘          │
└─────────────────────────────────────────────────────────┘
```

### Scraper modules

| Module | Description |
|---|---|
| `scrapers/pricing.py` | Captures product/service tiers and prices per competitor |
| `scrapers/products.py` | Lists services offered per competitor |
| `scrapers/snapshots.py` | Daily HTML capture + unified diff against prior day |
| `scrapers/reviews_trustpilot.py` | Trustpilot rating, review count, star distribution |
| `scrapers/reviews_google.py` | Google Reviews rating and review count |
| `scrapers/ab_tests.py` | Detects A/B testing frameworks (Optimizely, VWO, etc.) |

All scrapers follow a **fail-safe pattern**: a timeout or block on one competitor or one module does not stop the daily run. Errors are logged and the runner continues.

---

## Competitors Tracked

| Domain | Homepage |
|---|---|
| onwardticket.com | https://www.onwardticket.com |
| bestonwardticket.com | https://www.bestonwardticket.com |
| dummyticket.com | https://www.dummyticket.com |
| dummy-tickets.com | https://www.dummy-tickets.com |
| vizafly.com | https://www.vizafly.com |

---

## Quick Start

### Prerequisites

- Python 3.11+
- `pip` (or `pip3`)

### 1. Clone the repository

```bash
git clone <repo-url>
cd competitor-tracker
```

### 2. Create and activate a virtual environment

```bash
python3 -m venv .venv
source .venv/bin/activate   # macOS/Linux
.venv\Scripts\activate      # Windows
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure environment

```bash
cp .env.example .env
```

Edit `.env` and set at minimum:

```dotenv
DASHBOARD_PASSWORD=your-secure-password-here
SECRET_KEY=your-random-secret-key-here
```

To generate a strong `SECRET_KEY`:

```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```

### 5. Initialise the database

```bash
python3 init_db.py
```

### 6. Run the daily scraper

```bash
python3 run_daily.py
```

### 7. Start the dashboard

```bash
python3 -m dashboard.server
```

Open http://localhost:3001 in your browser and log in with your `DASHBOARD_PASSWORD`.

---

## Configuration

All configuration is via environment variables. Copy `.env.example` to `.env` and customise.

| Variable | Default | Description |
|---|---|---|
| `DASHBOARD_PASSWORD` | `changeme` | Shared password for the dashboard login page |
| `SECRET_KEY` | *(auto-generated)* | Flask session secret key. **Set this in production.** If left unset a new random key is generated at each startup, logging everyone out on restart. |
| `DASHBOARD_PORT` | `3001` | Port the Flask server listens on |
| `DB_PATH` | `./competitor_data.db` | Path to the SQLite database file |
| `USER_AGENT` | `Mozilla/5.0 …` | HTTP User-Agent sent by all scrapers |
| `REQUEST_TIMEOUT` | `30` | Per-request timeout in seconds |
| `REQUEST_DELAY` | `2` | Delay in seconds between requests to the same host |

---

## Running the Scrapers

### Full daily run (recommended)

```bash
python3 run_daily.py
```

This runs **all scrapers sequentially**. One scraper failing does not prevent the others from running. The script always exits with code `0`. Check `logs/daily_YYYY-MM-DD.log` for per-scraper status.

Example log output:

```
2026-02-23 06:00:01 INFO  Daily run started
2026-02-23 06:00:05 INFO  [pricing]   SUCCESS rows_inserted=18 duration=3.8s
2026-02-23 06:00:09 INFO  [products]  SUCCESS rows_inserted=24 duration=4.1s
2026-02-23 06:00:14 INFO  [snapshots] SUCCESS rows_inserted=10 duration=5.2s
2026-02-23 06:00:18 INFO  [trustpilot] SUCCESS rows_inserted=5 duration=4.0s
2026-02-23 06:00:21 INFO  [google]    FAILED  rows_inserted=0 duration=2.5s
2026-02-23 06:00:23 INFO  [ab_tests]  SUCCESS rows_inserted=3 duration=2.1s
2026-02-23 06:00:23 INFO  Daily run complete  successes=5 failures=1
```

### Run a single scraper

```bash
python3 -m scrapers.pricing
python3 -m scrapers.products
python3 -m scrapers.snapshots
python3 -m scrapers.reviews_trustpilot
python3 -m scrapers.reviews_google
python3 -m scrapers.ab_tests
```

---

## Dashboard

The dashboard is a Flask application serving a vanilla-JS single-page app.

### Start

```bash
python3 -m dashboard.server
# or
python3 dashboard/server.py
```

Dashboard available at: **http://localhost:3001**

### Authentication

All pages (except `/health`) require a valid session. The first request redirects to `/login`. Enter the password configured in `DASHBOARD_PASSWORD`. Sessions persist until the browser is closed or `/logout` is visited.

**Sharing with team members:** Share the URL and the password. There is a single shared credential — no per-user accounts.

### Tabs

| Tab | Description |
|---|---|
| **Pricing** | Current prices per competitor, historical trend chart, comparison matrix |
| **Products** | Competitor × product comparison matrix, full product catalog |
| **Diffs** | Daily website diffs with syntax-highlighted additions/removals |
| **Reviews** | Trustpilot + Google ratings and review-count trend charts |

### API Endpoints

All endpoints require authentication (session cookie). Use a browser session or pass the session cookie manually.

| Endpoint | Query params | Description |
|---|---|---|
| `GET /api/prices` | `competitor`, `date`, `start_date`, `end_date` | Pricing history |
| `GET /api/products` | `competitor`, `date`, `start_date`, `end_date` | Product catalog |
| `GET /api/reviews` | `competitor`, `date`, `start_date`, `end_date` | Review metrics |
| `GET /api/diffs` | `competitor`, `date`, `start_date`, `end_date` | Website diffs |
| `GET /api/ab-tests` | `competitor`, `date`, `start_date`, `end_date` | A/B tool detections |
| `GET /api/competitors` | — | Competitor list |
| `GET /health` | — | Health check (unauthenticated) |

Date params accept ISO 8601 dates (`YYYY-MM-DD`).

---

## Cron Setup

To run the daily scraper automatically at 05:00 UTC every day:

```bash
crontab -e
```

Add:

```cron
0 5 * * * /path/to/.venv/bin/python /path/to/competitor-tracker/run_daily.py >> /path/to/competitor-tracker/logs/cron.log 2>&1
```

Replace `/path/to/` with your actual paths.

### Keeping the dashboard running

Use `systemd`, `supervisor`, or `screen`/`tmux` to keep the Flask server running.

**systemd example** (`/etc/systemd/system/competitor-tracker.service`):

```ini
[Unit]
Description=Competitor Tracker Dashboard
After=network.target

[Service]
User=ubuntu
WorkingDirectory=/path/to/competitor-tracker
EnvironmentFile=/path/to/competitor-tracker/.env
ExecStart=/path/to/.venv/bin/python -m dashboard.server
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

Enable and start:

```bash
sudo systemctl enable competitor-tracker
sudo systemctl start competitor-tracker
```

---

## Running Tests

```bash
# Run all tests
pytest -v

# Run a specific module
pytest tests/test_dashboard_server.py -v

# Run with coverage (requires pytest-cov)
pip install pytest-cov
pytest --cov=. --cov-report=term-missing
```

Tests use an in-memory (or `tmp_path`) SQLite database and never hit the live competitor websites.

### Type checking

```bash
mypy .
```

The mypy configuration (`mypy.ini`) enforces strict checking on all non-scraper/non-dashboard modules. Tests and core library code must be fully annotated.

---

## Project Structure

```
competitor-tracker/
├── dashboard/
│   ├── __init__.py
│   ├── server.py          # Flask app factory and API routes
│   ├── static/
│   │   └── index.html     # Single-page dashboard (vanilla JS + Chart.js)
│   └── templates/
│       └── login.html     # Login page
├── database/
│   ├── __init__.py
│   └── schema.py          # SQLite DDL and table definitions
├── logs/                  # Daily run logs (gitignored)
├── scrapers/
│   ├── __init__.py
│   ├── ab_tests.py
│   ├── pricing.py
│   ├── products.py
│   ├── reviews_google.py
│   ├── reviews_trustpilot.py
│   └── snapshots.py
├── tests/
│   ├── test_ab_tests_scraper.py
│   ├── test_auth.py
│   ├── test_dashboard_frontend.py
│   ├── test_dashboard_s11.py
│   ├── test_dashboard_server.py
│   ├── test_init_db.py
│   ├── test_pricing_scraper.py
│   ├── test_products_scraper.py
│   ├── test_reviews_google.py
│   ├── test_reviews_trustpilot.py
│   ├── test_run_daily.py
│   └── test_snapshots_scraper.py
├── .env.example           # Environment variable template
├── .gitignore
├── competitor_data.db     # SQLite database (gitignored)
├── init_db.py             # Database initialisation script
├── mypy.ini
├── progress.txt           # Developer progress log
├── requirements.txt
├── run_daily.py           # Daily orchestrator script
└── README.md
```

---

## Database Schema

The SQLite database (`competitor_data.db`) contains the following tables:

### `competitors`
| Column | Type | Description |
|---|---|---|
| `id` | INTEGER PK | Auto-increment |
| `domain` | TEXT UNIQUE | e.g. `onwardticket.com` |
| `base_url` | TEXT | e.g. `https://www.onwardticket.com` |
| `created_at` | TEXT | ISO 8601 timestamp |

### `prices`
| Column | Type | Description |
|---|---|---|
| `id` | INTEGER PK | |
| `competitor_id` | INTEGER FK | → competitors.id |
| `scrape_date` | TEXT | YYYY-MM-DD |
| `scraped_at` | TEXT | ISO 8601 timestamp |
| `product_name` | TEXT | e.g. `Onward Ticket` |
| `tier_name` | TEXT | e.g. `Basic`, `Premium` |
| `currency` | TEXT | e.g. `USD` |
| `price_amount` | REAL | Numeric price |
| `bundle_info` | TEXT | Bundle description if applicable |
| `source_url` | TEXT | URL the price was scraped from |
| `raw_text` | TEXT | Raw price text captured |

### `products`
| Column | Type | Description |
|---|---|---|
| `id` | INTEGER PK | |
| `competitor_id` | INTEGER FK | |
| `scrape_date` | TEXT | YYYY-MM-DD |
| `product_name` | TEXT | |
| `product_type` | TEXT | e.g. `single`, `round_trip`, `bundle` |
| `description` | TEXT | |
| `is_bundle` | INTEGER | 0 or 1 |
| `source_url` | TEXT | |

### `snapshots`
| Column | Type | Description |
|---|---|---|
| `id` | INTEGER PK | |
| `competitor_id` | INTEGER FK | |
| `snapshot_date` | TEXT | YYYY-MM-DD |
| `page_type` | TEXT | e.g. `homepage`, `pricing` |
| `html_content` | TEXT | Raw HTML |
| `text_content` | TEXT | Stripped text |
| `url` | TEXT | Page URL |
| `created_at` | TEXT | |

### `diffs`
| Column | Type | Description |
|---|---|---|
| `id` | INTEGER PK | |
| `competitor_id` | INTEGER FK | |
| `diff_date` | TEXT | YYYY-MM-DD |
| `page_type` | TEXT | |
| `previous_snapshot_id` | INTEGER | |
| `current_snapshot_id` | INTEGER | |
| `diff_text` | TEXT | Unified diff output |
| `additions_count` | INTEGER | Lines added |
| `removals_count` | INTEGER | Lines removed |
| `created_at` | TEXT | |

### `reviews_trustpilot`
| Column | Type | Description |
|---|---|---|
| `id` | INTEGER PK | |
| `competitor_id` | INTEGER FK | |
| `scrape_date` | TEXT | YYYY-MM-DD |
| `overall_rating` | REAL | e.g. `4.3` |
| `review_count` | INTEGER | Total review count |
| `stars_1` … `stars_5` | INTEGER | Reviews per star level |
| `source_url` | TEXT | Trustpilot page URL |

### `reviews_google`
| Column | Type | Description |
|---|---|---|
| `id` | INTEGER PK | |
| `competitor_id` | INTEGER FK | |
| `scrape_date` | TEXT | YYYY-MM-DD |
| `overall_rating` | REAL | |
| `review_count` | INTEGER | |
| `source_url` | TEXT | |

### `ab_tests`
| Column | Type | Description |
|---|---|---|
| `id` | INTEGER PK | |
| `competitor_id` | INTEGER FK | |
| `scrape_date` | TEXT | YYYY-MM-DD |
| `page_url` | TEXT | URL scanned |
| `tool_name` | TEXT | e.g. `optimizely`, `vwo` |
| `detected` | INTEGER | 1 if detected |
| `evidence` | TEXT | Snippet from page source |

---

## Troubleshooting

### Dashboard shows "Incorrect password"
- Check that `DASHBOARD_PASSWORD` in your `.env` matches what you are entering.
- Passwords are compared with `secrets.compare_digest` (constant-time), so there is no race-condition; the password just needs to match exactly.

### Everyone gets logged out when the server restarts
- Set a persistent `SECRET_KEY` in `.env`. If unset, a new random key is generated on each startup, invalidating all existing sessions.

### Scrapers return no data
- Many competitor sites block automated requests. Scrapers log a warning and continue — check `logs/daily_YYYY-MM-DD.log` for `ERROR` lines.
- Increase `REQUEST_DELAY` to slow down requests and reduce the chance of being blocked.
- Some sites require a realistic `User-Agent`; update `USER_AGENT` in `.env` if needed.

### Database file not found
- Run `python3 init_db.py` to create and seed the database.

### `ModuleNotFoundError` when running scripts
- Make sure your virtual environment is activated: `source .venv/bin/activate`
- Run scripts from the repo root, not from inside subdirectories.

### Port 3001 already in use
- Change `DASHBOARD_PORT` in `.env`, then pass it to the server: `DASHBOARD_PORT=3002 python3 -m dashboard.server`
- Or kill the existing process: `lsof -ti:3001 | xargs kill`
