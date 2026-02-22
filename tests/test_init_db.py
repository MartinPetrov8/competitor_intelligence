from __future__ import annotations

import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class InitDbTests(unittest.TestCase):
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

    def test_init_db_creates_required_tables_and_competitors(self) -> None:
        result = self._run_init_db()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(self.db_path.exists())

        required_tables = {
            "competitors",
            "prices",
            "products",
            "snapshots",
            "diffs",
            "reviews_trustpilot",
            "reviews_google",
            "ab_tests",
        }

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table';")
            table_names = {row[0] for row in cursor.fetchall()}
            self.assertTrue(required_tables.issubset(table_names))

            competitors = conn.execute("SELECT domain, base_url FROM competitors ORDER BY domain;").fetchall()
            self.assertEqual(len(competitors), 5)
            self.assertIn(("onwardticket.com", "https://onwardticket.com"), competitors)
            self.assertIn(("vizafly.com", "https://vizafly.com"), competitors)

    def test_schema_indexes_exist_for_competitor_and_date_columns(self) -> None:
        result = self._run_init_db()
        self.assertEqual(result.returncode, 0, result.stderr)

        expected_indexes = {
            "idx_prices_competitor_date",
            "idx_products_competitor_date",
            "idx_snapshots_competitor_date",
            "idx_diffs_competitor_date",
            "idx_reviews_trustpilot_competitor_date",
            "idx_reviews_google_competitor_date",
            "idx_ab_tests_competitor_date",
        }

        with sqlite3.connect(self.db_path) as conn:
            indexes = conn.execute("SELECT name FROM sqlite_master WHERE type='index';").fetchall()
            index_names = {row[0] for row in indexes}

        self.assertTrue(expected_indexes.issubset(index_names))


if __name__ == "__main__":
    unittest.main()
