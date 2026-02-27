from __future__ import annotations

from typing import Final

COMPETITORS: Final[list[tuple[str, str]]] = [
    ("onwardticket.com", "https://onwardticket.com"),
    ("bestonwardticket.com", "https://bestonwardticket.com"),
    ("dummyticket.com", "https://dummyticket.com"),
    ("dummy-tickets.com", "https://dummy-tickets.com"),
    ("vizafly.com", "https://vizafly.com"),
]

TABLES_SQL: Final[list[str]] = [
    """
    CREATE TABLE IF NOT EXISTS competitors (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        domain TEXT NOT NULL UNIQUE,
        base_url TEXT NOT NULL,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS prices (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        competitor_id INTEGER NOT NULL,
        scrape_date TEXT NOT NULL,
        scraped_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        product_name TEXT NOT NULL,
        tier_name TEXT,
        currency TEXT,
        price_amount REAL,
        bundle_info TEXT,
        source_url TEXT,
        raw_text TEXT,
        FOREIGN KEY (competitor_id) REFERENCES competitors(id)
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS products (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        competitor_id INTEGER NOT NULL,
        scrape_date TEXT NOT NULL,
        scraped_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        product_name TEXT NOT NULL,
        product_type TEXT,
        description TEXT,
        is_bundle INTEGER NOT NULL DEFAULT 0,
        source_url TEXT,
        FOREIGN KEY (competitor_id) REFERENCES competitors(id)
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS snapshots (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        competitor_id INTEGER NOT NULL,
        scrape_date TEXT NOT NULL,
        scraped_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        page_type TEXT NOT NULL,
        page_url TEXT NOT NULL,
        html_content TEXT NOT NULL,
        content_hash TEXT,
        ab_test_signals TEXT,
        FOREIGN KEY (competitor_id) REFERENCES competitors(id)
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS diffs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        competitor_id INTEGER NOT NULL,
        diff_date TEXT NOT NULL,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        page_type TEXT NOT NULL,
        previous_snapshot_id INTEGER,
        current_snapshot_id INTEGER,
        diff_text TEXT,
        additions_count INTEGER,
        removals_count INTEGER,
        FOREIGN KEY (competitor_id) REFERENCES competitors(id),
        FOREIGN KEY (previous_snapshot_id) REFERENCES snapshots(id),
        FOREIGN KEY (current_snapshot_id) REFERENCES snapshots(id)
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS reviews_trustpilot (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        competitor_id INTEGER NOT NULL,
        scrape_date TEXT NOT NULL,
        scraped_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        overall_rating REAL,
        total_reviews INTEGER,
        rating_1 INTEGER,
        rating_2 INTEGER,
        rating_3 INTEGER,
        rating_4 INTEGER,
        rating_5 INTEGER,
        source_url TEXT,
        FOREIGN KEY (competitor_id) REFERENCES competitors(id)
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS reviews_google (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        competitor_id INTEGER NOT NULL,
        scrape_date TEXT NOT NULL,
        scraped_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        overall_rating REAL,
        total_reviews INTEGER,
        source_url TEXT,
        FOREIGN KEY (competitor_id) REFERENCES competitors(id)
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS ab_tests (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        competitor_id INTEGER NOT NULL,
        scrape_date TEXT NOT NULL,
        scraped_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        page_url TEXT NOT NULL,
        tool_name TEXT NOT NULL,
        detected INTEGER NOT NULL DEFAULT 0,
        evidence TEXT,
        FOREIGN KEY (competitor_id) REFERENCES competitors(id)
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS prices_v2 (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        competitor_id INTEGER NOT NULL,
        scrape_date TEXT NOT NULL,
        scraped_at TEXT NOT NULL,
        main_price REAL,
        currency TEXT NOT NULL DEFAULT 'USD',
        addons TEXT,
        source_url TEXT,
        UNIQUE(competitor_id, scrape_date),
        FOREIGN KEY (competitor_id) REFERENCES competitors(id)
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS products_v2 (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        competitor_id INTEGER NOT NULL,
        scrape_date TEXT NOT NULL,
        scraped_at TEXT NOT NULL,
        one_way_offered INTEGER NOT NULL DEFAULT 0,
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
    """,
    """
    CREATE TABLE IF NOT EXISTS reviews_sentiment (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        competitor_id INTEGER NOT NULL,
        scrape_date TEXT NOT NULL,
        scraped_at TEXT NOT NULL,
        stars_filter INTEGER NOT NULL,
        theme TEXT NOT NULL,
        mention_count INTEGER NOT NULL DEFAULT 1,
        sample_quotes TEXT,
        UNIQUE(competitor_id, scrape_date, stars_filter, theme),
        FOREIGN KEY (competitor_id) REFERENCES competitors(id)
    );
    """,
]

INDEXES_SQL: Final[list[str]] = [
    "CREATE INDEX IF NOT EXISTS idx_prices_competitor_date ON prices (competitor_id, scrape_date);",
    "CREATE INDEX IF NOT EXISTS idx_products_competitor_date ON products (competitor_id, scrape_date);",
    "CREATE INDEX IF NOT EXISTS idx_snapshots_competitor_date ON snapshots (competitor_id, scrape_date);",
    "CREATE INDEX IF NOT EXISTS idx_diffs_competitor_date ON diffs (competitor_id, diff_date);",
    "CREATE INDEX IF NOT EXISTS idx_reviews_trustpilot_competitor_date ON reviews_trustpilot (competitor_id, scrape_date);",
    "CREATE INDEX IF NOT EXISTS idx_reviews_google_competitor_date ON reviews_google (competitor_id, scrape_date);",
    "CREATE INDEX IF NOT EXISTS idx_ab_tests_competitor_date ON ab_tests (competitor_id, scrape_date);",
    "CREATE INDEX IF NOT EXISTS idx_prices_v2_competitor_date ON prices_v2 (competitor_id, scrape_date);",
    "CREATE INDEX IF NOT EXISTS idx_products_v2_competitor_date ON products_v2 (competitor_id, scrape_date);",
    "CREATE INDEX IF NOT EXISTS idx_reviews_sentiment_competitor_date ON reviews_sentiment (competitor_id, scrape_date);",
]
