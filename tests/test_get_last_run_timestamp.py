from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

from dashboard.server import DashboardStore
from init_db import init_database


@pytest.fixture
def test_db(tmp_path: Path) -> Path:
    """Create a test database with initialized schema."""
    db_path = tmp_path / "test.db"
    init_database(db_path)
    return db_path


class TestGetLastRunTimestamp:
    """Tests for DashboardStore.get_last_run_timestamp() method."""

    def test_get_last_run_timestamp_with_no_data(self, test_db: Path) -> None:
        """Test that get_last_run_timestamp returns None when all tables are empty."""
        store = DashboardStore(test_db)
        timestamp = store.get_last_run_timestamp()
        assert timestamp is None

    def test_get_last_run_timestamp_from_prices_v2_only(self, test_db: Path) -> None:
        """Test that get_last_run_timestamp returns timestamp from prices_v2 when only that table has data."""
        with sqlite3.connect(test_db) as conn:
            # Insert a competitor first
            conn.execute(
                "INSERT INTO competitors (domain, base_url) VALUES (?, ?)",
                ("test.com", "https://test.com"),
            )
            competitor_id = conn.execute("SELECT id FROM competitors WHERE domain = ?", ("test.com",)).fetchone()[0]
            
            # Insert into prices_v2
            test_timestamp = "2026-02-25T10:00:00+00:00"
            conn.execute(
                """INSERT INTO prices_v2 
                   (competitor_id, scrape_date, scraped_at, main_price, currency, source_url)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (competitor_id, "2026-02-25", test_timestamp, 100.0, "USD", "https://test.com"),
            )
        
        store = DashboardStore(test_db)
        timestamp = store.get_last_run_timestamp()
        assert timestamp == test_timestamp

    def test_get_last_run_timestamp_from_products_v2_only(self, test_db: Path) -> None:
        """Test that get_last_run_timestamp returns timestamp from products_v2 when only that table has data."""
        with sqlite3.connect(test_db) as conn:
            conn.execute(
                "INSERT INTO competitors (domain, base_url) VALUES (?, ?)",
                ("test.com", "https://test.com"),
            )
            competitor_id = conn.execute("SELECT id FROM competitors WHERE domain = ?", ("test.com",)).fetchone()[0]
            
            test_timestamp = "2026-02-25T11:00:00+00:00"
            conn.execute(
                """INSERT INTO products_v2 
                   (competitor_id, scrape_date, scraped_at, one_way_offered, round_trip_offered, hotel_offered, visa_letter_offered)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (competitor_id, "2026-02-25", test_timestamp, 1, 1, 0, 0),
            )
        
        store = DashboardStore(test_db)
        timestamp = store.get_last_run_timestamp()
        assert timestamp == test_timestamp

    def test_get_last_run_timestamp_from_reviews_trustpilot_only(self, test_db: Path) -> None:
        """Test that get_last_run_timestamp returns timestamp from reviews_trustpilot when only that table has data."""
        with sqlite3.connect(test_db) as conn:
            conn.execute(
                "INSERT INTO competitors (domain, base_url) VALUES (?, ?)",
                ("test.com", "https://test.com"),
            )
            competitor_id = conn.execute("SELECT id FROM competitors WHERE domain = ?", ("test.com",)).fetchone()[0]
            
            test_timestamp = "2026-02-25T12:00:00+00:00"
            conn.execute(
                """INSERT INTO reviews_trustpilot 
                   (competitor_id, scrape_date, scraped_at, overall_rating, source_url)
                   VALUES (?, ?, ?, ?, ?)""",
                (competitor_id, "2026-02-25", test_timestamp, 4.5, "https://trustpilot.com"),
            )
        
        store = DashboardStore(test_db)
        timestamp = store.get_last_run_timestamp()
        assert timestamp == test_timestamp

    def test_get_last_run_timestamp_from_reviews_google_only(self, test_db: Path) -> None:
        """Test that get_last_run_timestamp returns timestamp from reviews_google when only that table has data."""
        with sqlite3.connect(test_db) as conn:
            conn.execute(
                "INSERT INTO competitors (domain, base_url) VALUES (?, ?)",
                ("test.com", "https://test.com"),
            )
            competitor_id = conn.execute("SELECT id FROM competitors WHERE domain = ?", ("test.com",)).fetchone()[0]
            
            test_timestamp = "2026-02-25T13:00:00+00:00"
            conn.execute(
                """INSERT INTO reviews_google 
                   (competitor_id, scrape_date, scraped_at, overall_rating, source_url)
                   VALUES (?, ?, ?, ?, ?)""",
                (competitor_id, "2026-02-25", test_timestamp, 4.2, "https://google.com"),
            )
        
        store = DashboardStore(test_db)
        timestamp = store.get_last_run_timestamp()
        assert timestamp == test_timestamp

    def test_get_last_run_timestamp_from_ab_tests_only(self, test_db: Path) -> None:
        """Test that get_last_run_timestamp returns timestamp from ab_tests when only that table has data."""
        with sqlite3.connect(test_db) as conn:
            conn.execute(
                "INSERT INTO competitors (domain, base_url) VALUES (?, ?)",
                ("test.com", "https://test.com"),
            )
            competitor_id = conn.execute("SELECT id FROM competitors WHERE domain = ?", ("test.com",)).fetchone()[0]
            
            test_timestamp = "2026-02-25T14:00:00+00:00"
            conn.execute(
                """INSERT INTO ab_tests 
                   (competitor_id, scrape_date, scraped_at, page_url, tool_name, detected)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (competitor_id, "2026-02-25", test_timestamp, "https://test.com", "Optimizely", 1),
            )
        
        store = DashboardStore(test_db)
        timestamp = store.get_last_run_timestamp()
        assert timestamp == test_timestamp

    def test_get_last_run_timestamp_from_snapshots_only(self, test_db: Path) -> None:
        """Test that get_last_run_timestamp returns timestamp from snapshots when only that table has data."""
        with sqlite3.connect(test_db) as conn:
            conn.execute(
                "INSERT INTO competitors (domain, base_url) VALUES (?, ?)",
                ("test.com", "https://test.com"),
            )
            competitor_id = conn.execute("SELECT id FROM competitors WHERE domain = ?", ("test.com",)).fetchone()[0]
            
            test_timestamp = "2026-02-25T15:00:00+00:00"
            conn.execute(
                """INSERT INTO snapshots 
                   (competitor_id, scrape_date, scraped_at, page_url, page_type, html_content)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (competitor_id, "2026-02-25", test_timestamp, "https://test.com", "homepage", "<html></html>"),
            )
        
        store = DashboardStore(test_db)
        timestamp = store.get_last_run_timestamp()
        assert timestamp == test_timestamp

    def test_get_last_run_timestamp_returns_maximum_across_all_tables(self, test_db: Path) -> None:
        """Test that get_last_run_timestamp returns the maximum timestamp across all six tables."""
        with sqlite3.connect(test_db) as conn:
            conn.execute(
                "INSERT INTO competitors (domain, base_url) VALUES (?, ?)",
                ("test.com", "https://test.com"),
            )
            competitor_id = conn.execute("SELECT id FROM competitors WHERE domain = ?", ("test.com",)).fetchone()[0]
            
            # Insert data with different timestamps across all tables
            conn.execute(
                """INSERT INTO prices_v2 
                   (competitor_id, scrape_date, scraped_at, main_price, currency, source_url)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (competitor_id, "2026-02-25", "2026-02-25T10:00:00+00:00", 100.0, "USD", "https://test.com"),
            )
            conn.execute(
                """INSERT INTO products_v2 
                   (competitor_id, scrape_date, scraped_at, one_way_offered, round_trip_offered, hotel_offered, visa_letter_offered)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (competitor_id, "2026-02-25", "2026-02-25T11:00:00+00:00", 1, 1, 0, 0),
            )
            conn.execute(
                """INSERT INTO reviews_trustpilot 
                   (competitor_id, scrape_date, scraped_at, overall_rating, source_url)
                   VALUES (?, ?, ?, ?, ?)""",
                (competitor_id, "2026-02-25", "2026-02-25T12:00:00+00:00", 4.5, "https://trustpilot.com"),
            )
            conn.execute(
                """INSERT INTO reviews_google 
                   (competitor_id, scrape_date, scraped_at, overall_rating, source_url)
                   VALUES (?, ?, ?, ?, ?)""",
                (competitor_id, "2026-02-25", "2026-02-25T16:30:00+00:00", 4.2, "https://google.com"),
            )
            conn.execute(
                """INSERT INTO ab_tests 
                   (competitor_id, scrape_date, scraped_at, page_url, tool_name, detected)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (competitor_id, "2026-02-25", "2026-02-25T14:00:00+00:00", "https://test.com", "Optimizely", 1),
            )
            conn.execute(
                """INSERT INTO snapshots 
                   (competitor_id, scrape_date, scraped_at, page_url, page_type, html_content)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (competitor_id, "2026-02-25", "2026-02-25T15:00:00+00:00", "https://test.com", "homepage", "<html></html>"),
            )
        
        store = DashboardStore(test_db)
        timestamp = store.get_last_run_timestamp()
        # The maximum timestamp should be from reviews_google at 16:30
        assert timestamp == "2026-02-25T16:30:00+00:00"

    def test_get_last_run_timestamp_with_multiple_rows_per_table(self, test_db: Path) -> None:
        """Test that get_last_run_timestamp correctly finds max when tables have multiple rows."""
        with sqlite3.connect(test_db) as conn:
            conn.execute(
                "INSERT INTO competitors (domain, base_url) VALUES (?, ?)",
                ("test.com", "https://test.com"),
            )
            competitor_id = conn.execute("SELECT id FROM competitors WHERE domain = ?", ("test.com",)).fetchone()[0]
            
            # Insert multiple rows in prices_v2 with different timestamps
            timestamps = [
                "2026-02-23T10:00:00+00:00",
                "2026-02-24T10:00:00+00:00",
                "2026-02-25T20:45:00+00:00",  # This is the maximum
            ]
            for i, ts in enumerate(timestamps):
                conn.execute(
                    """INSERT INTO prices_v2 
                       (competitor_id, scrape_date, scraped_at, main_price, currency, source_url)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (competitor_id, f"2026-02-{23+i}", ts, 100.0 + i, "USD", "https://test.com"),
                )
        
        store = DashboardStore(test_db)
        timestamp = store.get_last_run_timestamp()
        assert timestamp == "2026-02-25T20:45:00+00:00"

    def test_get_last_run_timestamp_handles_database_error(self, tmp_path: Path) -> None:
        """Test that get_last_run_timestamp raises sqlite3.Error on database failure."""
        db_path = tmp_path / "broken.db"
        # Create a database without the required tables
        with sqlite3.connect(db_path) as conn:
            conn.execute("CREATE TABLE dummy (id INTEGER)")
        
        store = DashboardStore(db_path)
        with pytest.raises(sqlite3.Error):
            store.get_last_run_timestamp()

    def test_get_last_run_timestamp_returns_string_or_none(self, test_db: Path) -> None:
        """Test that get_last_run_timestamp returns str or None type."""
        store = DashboardStore(test_db)
        timestamp = store.get_last_run_timestamp()
        assert timestamp is None or isinstance(timestamp, str)

    def test_get_last_run_timestamp_with_mixed_null_and_valid_timestamps(self, test_db: Path) -> None:
        """Test that get_last_run_timestamp handles tables with NULL timestamps correctly."""
        with sqlite3.connect(test_db) as conn:
            conn.execute(
                "INSERT INTO competitors (domain, base_url) VALUES (?, ?)",
                ("test.com", "https://test.com"),
            )
            competitor_id = conn.execute("SELECT id FROM competitors WHERE domain = ?", ("test.com",)).fetchone()[0]
            
            # Insert into snapshots with a valid timestamp
            test_timestamp = "2026-02-25T18:00:00+00:00"
            conn.execute(
                """INSERT INTO snapshots 
                   (competitor_id, scrape_date, scraped_at, page_url, page_type, html_content)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (competitor_id, "2026-02-25", test_timestamp, "https://test.com", "homepage", "<html></html>"),
            )
            # Other tables remain empty (NULL max values)
        
        store = DashboardStore(test_db)
        timestamp = store.get_last_run_timestamp()
        assert timestamp == test_timestamp
