from __future__ import annotations

import sqlite3
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


class TestGetScraperCount:
    """Tests for DashboardStore.get_scraper_count() method."""

    def test_get_scraper_count_with_default_competitors(self, test_db: Path) -> None:
        """Test that get_scraper_count returns 5 for the default seeded competitors."""
        store = DashboardStore(test_db)
        count = store.get_scraper_count()
        assert count == 5

    def test_get_scraper_count_with_empty_table(self, tmp_path: Path) -> None:
        """Test that get_scraper_count returns 0 when competitors table is empty."""
        db_path = tmp_path / "empty.db"
        # Create schema but don't seed competitors
        with sqlite3.connect(db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS competitors (
                    id INTEGER PRIMARY KEY,
                    domain TEXT NOT NULL UNIQUE,
                    base_url TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT (datetime('now'))
                )
            """)
        
        store = DashboardStore(db_path)
        count = store.get_scraper_count()
        assert count == 0

    def test_get_scraper_count_with_custom_competitors(self, tmp_path: Path) -> None:
        """Test that get_scraper_count returns correct count after adding competitors."""
        db_path = tmp_path / "custom.db"
        # Create schema
        with sqlite3.connect(db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS competitors (
                    id INTEGER PRIMARY KEY,
                    domain TEXT NOT NULL UNIQUE,
                    base_url TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT (datetime('now'))
                )
            """)
            # Insert 3 custom competitors
            conn.executemany(
                "INSERT INTO competitors (domain, base_url) VALUES (?, ?)",
                [
                    ("example1.com", "https://example1.com"),
                    ("example2.com", "https://example2.com"),
                    ("example3.com", "https://example3.com"),
                ],
            )
        
        store = DashboardStore(db_path)
        count = store.get_scraper_count()
        assert count == 3

    def test_get_scraper_count_handles_database_error(self, tmp_path: Path) -> None:
        """Test that get_scraper_count raises sqlite3.Error on database failure."""
        db_path = tmp_path / "broken.db"
        # Create a database without the competitors table
        with sqlite3.connect(db_path) as conn:
            conn.execute("CREATE TABLE dummy (id INTEGER)")
        
        store = DashboardStore(db_path)
        with pytest.raises(sqlite3.Error):
            store.get_scraper_count()

    def test_get_scraper_count_returns_integer(self, test_db: Path) -> None:
        """Test that get_scraper_count returns an integer type."""
        store = DashboardStore(test_db)
        count = store.get_scraper_count()
        assert isinstance(count, int)
