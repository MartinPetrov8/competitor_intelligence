from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from init_db import init_database


class HealthEndpointSchemaTests(unittest.TestCase):
    """Verify database schema supports health endpoint requirements."""

    def setUp(self) -> None:
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp_dir.name) / "test_health.db"
        init_database(self.db_path)

    def tearDown(self) -> None:
        self.tmp_dir.cleanup()

    def test_competitors_table_exists(self) -> None:
        """Competitors table must exist for scraper count."""
        with sqlite3.connect(str(self.db_path)) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='competitors'"
            )
            result = cursor.fetchone()
            self.assertIsNotNone(result, "competitors table must exist")

    def test_competitors_table_queryable(self) -> None:
        """Competitors table must be queryable for COUNT(*)."""
        with sqlite3.connect(str(self.db_path)) as conn:
            cursor = conn.cursor()
            # Should not raise an error
            cursor.execute("SELECT COUNT(*) FROM competitors")
            count = cursor.fetchone()[0]
            # Should have 5 seeded competitors
            self.assertEqual(count, 5, "Expected 5 competitors seeded")

    def test_competitors_table_has_required_columns(self) -> None:
        """Competitors table must have id, domain, base_url columns."""
        with sqlite3.connect(str(self.db_path)) as conn:
            cursor = conn.cursor()
            cursor.execute("PRAGMA table_info(competitors)")
            columns = {row[1] for row in cursor.fetchall()}
            self.assertIn("id", columns)
            self.assertIn("domain", columns)
            self.assertIn("base_url", columns)

    def test_prices_v2_has_scraped_at(self) -> None:
        """prices_v2 table must have scraped_at for last_run timestamp."""
        with sqlite3.connect(str(self.db_path)) as conn:
            cursor = conn.cursor()
            cursor.execute("PRAGMA table_info(prices_v2)")
            columns = {row[1] for row in cursor.fetchall()}
            self.assertIn(
                "scraped_at",
                columns,
                "prices_v2 must have scraped_at column for health endpoint",
            )

    def test_products_v2_has_scraped_at(self) -> None:
        """products_v2 table must have scraped_at for last_run timestamp."""
        with sqlite3.connect(str(self.db_path)) as conn:
            cursor = conn.cursor()
            cursor.execute("PRAGMA table_info(products_v2)")
            columns = {row[1] for row in cursor.fetchall()}
            self.assertIn(
                "scraped_at",
                columns,
                "products_v2 must have scraped_at column for health endpoint",
            )

    def test_reviews_trustpilot_has_scraped_at(self) -> None:
        """reviews_trustpilot table must have scraped_at for last_run timestamp."""
        with sqlite3.connect(str(self.db_path)) as conn:
            cursor = conn.cursor()
            cursor.execute("PRAGMA table_info(reviews_trustpilot)")
            columns = {row[1] for row in cursor.fetchall()}
            self.assertIn(
                "scraped_at",
                columns,
                "reviews_trustpilot must have scraped_at column for health endpoint",
            )

    def test_reviews_google_has_scraped_at(self) -> None:
        """reviews_google table must have scraped_at for last_run timestamp."""
        with sqlite3.connect(str(self.db_path)) as conn:
            cursor = conn.cursor()
            cursor.execute("PRAGMA table_info(reviews_google)")
            columns = {row[1] for row in cursor.fetchall()}
            self.assertIn(
                "scraped_at",
                columns,
                "reviews_google must have scraped_at column for health endpoint",
            )

    def test_ab_tests_has_scraped_at(self) -> None:
        """ab_tests table must have scraped_at for last_run timestamp."""
        with sqlite3.connect(str(self.db_path)) as conn:
            cursor = conn.cursor()
            cursor.execute("PRAGMA table_info(ab_tests)")
            columns = {row[1] for row in cursor.fetchall()}
            self.assertIn(
                "scraped_at",
                columns,
                "ab_tests must have scraped_at column for health endpoint",
            )

    def test_snapshots_has_scraped_at(self) -> None:
        """snapshots table must have scraped_at for last_run timestamp."""
        with sqlite3.connect(str(self.db_path)) as conn:
            cursor = conn.cursor()
            cursor.execute("PRAGMA table_info(snapshots)")
            columns = {row[1] for row in cursor.fetchall()}
            self.assertIn(
                "scraped_at",
                columns,
                "snapshots must have scraped_at column for health endpoint",
            )

    def test_all_scraper_tables_exist(self) -> None:
        """All scraper tables required for health check must exist."""
        expected_tables = {
            "prices_v2",
            "products_v2",
            "reviews_trustpilot",
            "reviews_google",
            "ab_tests",
            "snapshots",
        }
        with sqlite3.connect(str(self.db_path)) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
            actual_tables = {row[0] for row in cursor.fetchall()}
            for table in expected_tables:
                self.assertIn(
                    table,
                    actual_tables,
                    f"Scraper table {table} must exist for health endpoint",
                )

    def test_can_query_max_scraped_at_across_all_tables(self) -> None:
        """Must be able to query MAX(scraped_at) from all scraper tables."""
        scraper_tables = [
            "prices_v2",
            "products_v2",
            "reviews_trustpilot",
            "reviews_google",
            "ab_tests",
            "snapshots",
        ]
        with sqlite3.connect(str(self.db_path)) as conn:
            cursor = conn.cursor()
            for table in scraper_tables:
                # Should not raise an error even on empty table
                cursor.execute(f"SELECT MAX(scraped_at) FROM {table}")
                result = cursor.fetchone()
                # Empty table returns (None,)
                self.assertIsNotNone(
                    result, f"MAX(scraped_at) query on {table} must succeed"
                )


if __name__ == "__main__":
    unittest.main()
