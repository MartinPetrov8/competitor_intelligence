from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from init_db import init_database


class PricesV2SchemaTests(unittest.TestCase):
    """Tests for the prices_v2 table schema."""

    def setUp(self) -> None:
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp_dir.name) / "test_competitor_data.db"
        init_database(self.db_path)

    def tearDown(self) -> None:
        self.tmp_dir.cleanup()

    def _columns(self, conn: sqlite3.Connection, table: str) -> set[str]:
        rows = conn.execute(f"PRAGMA table_info({table});").fetchall()
        return {row[1] for row in rows}

    def test_prices_v2_table_exists(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table';"
                ).fetchall()
            }
        self.assertIn("prices_v2", tables)

    def test_prices_v2_has_required_columns(self) -> None:
        required = {
            "id",
            "competitor_id",
            "scrape_date",
            "scraped_at",
            "main_price",
            "currency",
            "addons",
            "source_url",
        }
        with sqlite3.connect(self.db_path) as conn:
            cols = self._columns(conn, "prices_v2")
        self.assertTrue(required.issubset(cols), f"Missing columns: {required - cols}")

    def test_prices_v2_unique_constraint_enforced(self) -> None:
        """Only one row allowed per competitor per scrape_date."""
        with sqlite3.connect(self.db_path) as conn:
            competitor_id = conn.execute(
                "SELECT id FROM competitors LIMIT 1;"
            ).fetchone()[0]

            conn.execute(
                """
                INSERT INTO prices_v2 (competitor_id, scrape_date, scraped_at, main_price, currency)
                VALUES (?, '2026-02-23', '2026-02-23T12:00:00', 14.99, 'USD')
                """,
                (competitor_id,),
            )
            conn.commit()

            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute(
                    """
                    INSERT INTO prices_v2 (competitor_id, scrape_date, scraped_at, main_price, currency)
                    VALUES (?, '2026-02-23', '2026-02-23T13:00:00', 12.99, 'USD')
                    """,
                    (competitor_id,),
                )

    def test_prices_v2_insert_or_replace_updates_row(self) -> None:
        """INSERT OR REPLACE updates the existing row on conflict."""
        with sqlite3.connect(self.db_path) as conn:
            competitor_id = conn.execute(
                "SELECT id FROM competitors LIMIT 1;"
            ).fetchone()[0]

            conn.execute(
                """
                INSERT OR REPLACE INTO prices_v2
                    (competitor_id, scrape_date, scraped_at, main_price, currency)
                VALUES (?, '2026-02-23', '2026-02-23T12:00:00', 14.99, 'USD')
                """,
                (competitor_id,),
            )
            conn.execute(
                """
                INSERT OR REPLACE INTO prices_v2
                    (competitor_id, scrape_date, scraped_at, main_price, currency)
                VALUES (?, '2026-02-23', '2026-02-23T13:00:00', 12.99, 'USD')
                """,
                (competitor_id,),
            )
            conn.commit()

            rows = conn.execute(
                "SELECT COUNT(*) FROM prices_v2 WHERE competitor_id=? AND scrape_date='2026-02-23';",
                (competitor_id,),
            ).fetchone()[0]
            self.assertEqual(rows, 1)

            price = conn.execute(
                "SELECT main_price FROM prices_v2 WHERE competitor_id=? AND scrape_date='2026-02-23';",
                (competitor_id,),
            ).fetchone()[0]
            self.assertAlmostEqual(price, 12.99)

    def test_prices_v2_addons_stores_valid_json(self) -> None:
        """addons column can store and retrieve a JSON array."""
        addons = json.dumps([
            {"name": "Round trip", "price": 7.0},
            {"name": "Extended validity", "price": 10.0},
        ])
        with sqlite3.connect(self.db_path) as conn:
            competitor_id = conn.execute(
                "SELECT id FROM competitors LIMIT 1;"
            ).fetchone()[0]
            conn.execute(
                """
                INSERT INTO prices_v2
                    (competitor_id, scrape_date, scraped_at, main_price, currency, addons)
                VALUES (?, '2026-02-23', '2026-02-23T12:00:00', 14.99, 'USD', ?)
                """,
                (competitor_id, addons),
            )
            conn.commit()

            stored = conn.execute(
                "SELECT addons FROM prices_v2 WHERE competitor_id=? AND scrape_date='2026-02-23';",
                (competitor_id,),
            ).fetchone()[0]

        parsed = json.loads(stored)
        self.assertEqual(len(parsed), 2)
        self.assertEqual(parsed[0]["name"], "Round trip")
        self.assertAlmostEqual(parsed[0]["price"], 7.0)

    def test_prices_v2_currency_defaults_to_usd(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            competitor_id = conn.execute(
                "SELECT id FROM competitors LIMIT 1;"
            ).fetchone()[0]
            conn.execute(
                """
                INSERT INTO prices_v2
                    (competitor_id, scrape_date, scraped_at, main_price)
                VALUES (?, '2026-02-23', '2026-02-23T12:00:00', 14.99)
                """,
                (competitor_id,),
            )
            conn.commit()

            currency = conn.execute(
                "SELECT currency FROM prices_v2 WHERE competitor_id=? AND scrape_date='2026-02-23';",
                (competitor_id,),
            ).fetchone()[0]
        self.assertEqual(currency, "USD")

    def test_prices_v2_index_exists(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            indexes = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='index';"
                ).fetchall()
            }
        self.assertIn("idx_prices_v2_competitor_date", indexes)

    def test_prices_v2_allows_multiple_competitors_same_date(self) -> None:
        """Different competitors can have rows for the same scrape_date."""
        with sqlite3.connect(self.db_path) as conn:
            competitors = conn.execute(
                "SELECT id FROM competitors LIMIT 2;"
            ).fetchall()
            self.assertGreaterEqual(len(competitors), 2)
            cid1, cid2 = competitors[0][0], competitors[1][0]

            conn.execute(
                """
                INSERT INTO prices_v2
                    (competitor_id, scrape_date, scraped_at, main_price, currency)
                VALUES (?, '2026-02-23', '2026-02-23T12:00:00', 14.99, 'USD')
                """,
                (cid1,),
            )
            conn.execute(
                """
                INSERT INTO prices_v2
                    (competitor_id, scrape_date, scraped_at, main_price, currency)
                VALUES (?, '2026-02-23', '2026-02-23T12:00:00', 19.99, 'USD')
                """,
                (cid2,),
            )
            conn.commit()

            count = conn.execute(
                "SELECT COUNT(*) FROM prices_v2 WHERE scrape_date='2026-02-23';"
            ).fetchone()[0]
        self.assertEqual(count, 2)


class ProductsV2SchemaTests(unittest.TestCase):
    """Tests for the products_v2 table schema."""

    def setUp(self) -> None:
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp_dir.name) / "test_competitor_data.db"
        init_database(self.db_path)

    def tearDown(self) -> None:
        self.tmp_dir.cleanup()

    def _columns(self, conn: sqlite3.Connection, table: str) -> set[str]:
        rows = conn.execute(f"PRAGMA table_info({table});").fetchall()
        return {row[1] for row in rows}

    def test_products_v2_table_exists(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table';"
                ).fetchall()
            }
        self.assertIn("products_v2", tables)

    def test_products_v2_has_required_columns(self) -> None:
        required = {
            "id",
            "competitor_id",
            "scrape_date",
            "scraped_at",
            "one_way_offered",
            "one_way_price",
            "round_trip_offered",
            "round_trip_price",
            "hotel_offered",
            "hotel_price",
            "visa_letter_offered",
            "visa_letter_price",
        }
        with sqlite3.connect(self.db_path) as conn:
            cols = self._columns(conn, "products_v2")
        self.assertTrue(required.issubset(cols), f"Missing columns: {required - cols}")

    def test_products_v2_unique_constraint_enforced(self) -> None:
        """Only one row allowed per competitor per scrape_date."""
        with sqlite3.connect(self.db_path) as conn:
            competitor_id = conn.execute(
                "SELECT id FROM competitors LIMIT 1;"
            ).fetchone()[0]

            conn.execute(
                """
                INSERT INTO products_v2
                    (competitor_id, scrape_date, scraped_at,
                     one_way_offered, round_trip_offered, hotel_offered, visa_letter_offered)
                VALUES (?, '2026-02-23', '2026-02-23T12:00:00', 1, 0, 0, 0)
                """,
                (competitor_id,),
            )
            conn.commit()

            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute(
                    """
                    INSERT INTO products_v2
                        (competitor_id, scrape_date, scraped_at,
                         one_way_offered, round_trip_offered, hotel_offered, visa_letter_offered)
                    VALUES (?, '2026-02-23', '2026-02-23T13:00:00', 1, 1, 0, 0)
                    """,
                    (competitor_id,),
                )

    def test_products_v2_boolean_defaults_are_false(self) -> None:
        """All offered flags default to 0 (false) when not specified."""
        with sqlite3.connect(self.db_path) as conn:
            competitor_id = conn.execute(
                "SELECT id FROM competitors LIMIT 1;"
            ).fetchone()[0]
            conn.execute(
                """
                INSERT INTO products_v2 (competitor_id, scrape_date, scraped_at)
                VALUES (?, '2026-02-23', '2026-02-23T12:00:00')
                """,
                (competitor_id,),
            )
            conn.commit()

            row = conn.execute(
                """
                SELECT one_way_offered, round_trip_offered, hotel_offered, visa_letter_offered
                FROM products_v2
                WHERE competitor_id=? AND scrape_date='2026-02-23';
                """,
                (competitor_id,),
            ).fetchone()

        self.assertEqual(row[0], 0)
        self.assertEqual(row[1], 0)
        self.assertEqual(row[2], 0)
        self.assertEqual(row[3], 0)

    def test_products_v2_full_row_round_trip(self) -> None:
        """All fields can be written and read back correctly."""
        with sqlite3.connect(self.db_path) as conn:
            competitor_id = conn.execute(
                "SELECT id FROM competitors LIMIT 1;"
            ).fetchone()[0]
            conn.execute(
                """
                INSERT INTO products_v2
                    (competitor_id, scrape_date, scraped_at,
                     one_way_offered, one_way_price,
                     round_trip_offered, round_trip_price,
                     hotel_offered, hotel_price,
                     visa_letter_offered, visa_letter_price)
                VALUES (?, '2026-02-23', '2026-02-23T12:00:00',
                        1, 14.99, 1, 21.99, 0, NULL, 1, 9.99)
                """,
                (competitor_id,),
            )
            conn.commit()

            row = conn.execute(
                """
                SELECT one_way_offered, one_way_price,
                       round_trip_offered, round_trip_price,
                       hotel_offered, hotel_price,
                       visa_letter_offered, visa_letter_price
                FROM products_v2
                WHERE competitor_id=? AND scrape_date='2026-02-23';
                """,
                (competitor_id,),
            ).fetchone()

        self.assertEqual(row[0], 1)
        self.assertAlmostEqual(row[1], 14.99)
        self.assertEqual(row[2], 1)
        self.assertAlmostEqual(row[3], 21.99)
        self.assertEqual(row[4], 0)
        self.assertIsNone(row[5])
        self.assertEqual(row[6], 1)
        self.assertAlmostEqual(row[7], 9.99)

    def test_products_v2_insert_or_ignore_preserves_first_row(self) -> None:
        """INSERT OR IGNORE keeps existing row on conflict."""
        with sqlite3.connect(self.db_path) as conn:
            competitor_id = conn.execute(
                "SELECT id FROM competitors LIMIT 1;"
            ).fetchone()[0]

            conn.execute(
                """
                INSERT OR IGNORE INTO products_v2
                    (competitor_id, scrape_date, scraped_at, one_way_offered)
                VALUES (?, '2026-02-23', '2026-02-23T12:00:00', 1)
                """,
                (competitor_id,),
            )
            conn.execute(
                """
                INSERT OR IGNORE INTO products_v2
                    (competitor_id, scrape_date, scraped_at, one_way_offered)
                VALUES (?, '2026-02-23', '2026-02-23T13:00:00', 0)
                """,
                (competitor_id,),
            )
            conn.commit()

            row = conn.execute(
                "SELECT one_way_offered FROM products_v2 WHERE competitor_id=? AND scrape_date='2026-02-23';",
                (competitor_id,),
            ).fetchone()
        # Original row preserved (one_way_offered=1)
        self.assertEqual(row[0], 1)

    def test_products_v2_index_exists(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            indexes = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='index';"
                ).fetchall()
            }
        self.assertIn("idx_products_v2_competitor_date", indexes)

    def test_products_v2_allows_multiple_competitors_same_date(self) -> None:
        """Different competitors can have rows for the same scrape_date."""
        with sqlite3.connect(self.db_path) as conn:
            competitors = conn.execute(
                "SELECT id FROM competitors LIMIT 3;"
            ).fetchall()
            self.assertGreaterEqual(len(competitors), 3)

            for cid_row in competitors:
                conn.execute(
                    """
                    INSERT INTO products_v2
                        (competitor_id, scrape_date, scraped_at, one_way_offered)
                    VALUES (?, '2026-02-23', '2026-02-23T12:00:00', 1)
                    """,
                    (cid_row[0],),
                )
            conn.commit()

            count = conn.execute(
                "SELECT COUNT(*) FROM products_v2 WHERE scrape_date='2026-02-23';"
            ).fetchone()[0]
        self.assertEqual(count, 3)


class InitDbV2IntegrationTests(unittest.TestCase):
    """Integration tests: init_db.py creates both v2 tables via subprocess."""

    def setUp(self) -> None:
        self.repo_root = Path(__file__).resolve().parents[1]
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp_dir.name) / "test_competitor_data.db"

    def tearDown(self) -> None:
        self.tmp_dir.cleanup()

    def _run_init_db(self) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "init_db.py", "--db-path", str(self.db_path)],
            cwd=self.repo_root,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_init_db_creates_prices_v2_and_products_v2(self) -> None:
        result = self._run_init_db()
        self.assertEqual(result.returncode, 0, result.stderr)

        with sqlite3.connect(self.db_path) as conn:
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table';"
                ).fetchall()
            }

        self.assertIn("prices_v2", tables)
        self.assertIn("products_v2", tables)

    def test_init_db_v2_indexes_created(self) -> None:
        result = self._run_init_db()
        self.assertEqual(result.returncode, 0, result.stderr)

        with sqlite3.connect(self.db_path) as conn:
            indexes = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='index';"
                ).fetchall()
            }

        self.assertIn("idx_prices_v2_competitor_date", indexes)
        self.assertIn("idx_products_v2_competitor_date", indexes)

    def test_init_db_is_idempotent(self) -> None:
        """Running init_db twice does not raise errors."""
        result1 = self._run_init_db()
        result2 = self._run_init_db()
        self.assertEqual(result1.returncode, 0, result1.stderr)
        self.assertEqual(result2.returncode, 0, result2.stderr)


if __name__ == "__main__":
    unittest.main()
