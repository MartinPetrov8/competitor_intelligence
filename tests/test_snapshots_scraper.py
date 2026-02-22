from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import requests

from init_db import init_database
from scrapers.snapshots import (
    REQUEST_TIMEOUT_SECONDS,
    _build_unified_diff,
    scrape_snapshots,
)


class MockResponse:
    def __init__(self, text: str, status_code: int = 200) -> None:
        self.text = text
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")


class SnapshotScraperTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp_dir.name) / "test_competitor_data.db"
        init_database(self.db_path)

    def tearDown(self) -> None:
        self.tmp_dir.cleanup()

    def test_build_unified_diff_ignores_whitespace_and_timestamps(self) -> None:
        previous = """
        <div>
          Last updated: 2026-02-22T09:10:11Z
          Price now $12
        </div>
        """
        current = """
        <div>Last updated: 2026-02-23T10:11:12Z
        Price   now    $12
        </div>
        """

        diff = _build_unified_diff(previous, current, "prev", "curr")
        self.assertEqual(diff, "")

    def test_scrape_snapshots_stores_html_and_diffs_between_runs(self) -> None:
        calls: list[tuple[str, int]] = []

        def fake_get_first(url: str, timeout: int) -> MockResponse:
            calls.append((url, timeout))
            if "bestonwardticket.com" in url:
                raise requests.Timeout("timed out")
            html = f"<html><body><h1>{url}</h1><p>status initial</p></body></html>"
            return MockResponse(html)

        with patch("requests.Session.get", side_effect=fake_get_first), patch(
            "scrapers.snapshots.datetime"
        ) as mock_datetime:
            from datetime import UTC, datetime

            mock_datetime.now.return_value = datetime(2026, 2, 22, 9, 0, tzinfo=UTC)
            first_success = scrape_snapshots(self.db_path)

        self.assertTrue(first_success)
        self.assertTrue(calls)
        self.assertTrue(all(timeout == REQUEST_TIMEOUT_SECONDS for _, timeout in calls))

        def fake_get_second(url: str, timeout: int) -> MockResponse:
            if "bestonwardticket.com" in url:
                return MockResponse(f"<html><body><h1>{url}</h1><p>stable</p></body></html>")
            if "onwardticket.com/pricing" in url:
                return MockResponse(
                    "<html><body><h1>pricing</h1><p>status changed</p>"
                    "<p>generated 2026-02-23T10:20:30Z</p></body></html>"
                )
            return MockResponse(f"<html><body><h1>{url}</h1><p>status initial</p></body></html>")

        with patch("requests.Session.get", side_effect=fake_get_second), patch(
            "scrapers.snapshots.datetime"
        ) as mock_datetime:
            from datetime import UTC, datetime

            mock_datetime.now.return_value = datetime(2026, 2, 23, 9, 0, tzinfo=UTC)
            second_success = scrape_snapshots(self.db_path)

        self.assertTrue(second_success)

        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            snapshots = conn.execute(
                "SELECT competitor_id, page_url, html_content, scraped_at FROM snapshots"
            ).fetchall()
            diffs = conn.execute(
                "SELECT competitor_id, page_type, diff_text, additions_count, removals_count FROM diffs"
            ).fetchall()

        self.assertGreaterEqual(len(snapshots), 1)
        self.assertGreaterEqual(len(diffs), 1)

        for snapshot in snapshots:
            self.assertIsNotNone(snapshot["competitor_id"])
            self.assertTrue(snapshot["page_url"])
            self.assertTrue(snapshot["html_content"])
            self.assertIsNotNone(snapshot["scraped_at"])

        changed_pricing_diff = [row for row in diffs if row["page_type"] == "pricing"]
        self.assertTrue(changed_pricing_diff)
        self.assertTrue(any("status changed" in row["diff_text"] for row in changed_pricing_diff))
        self.assertTrue(all(int(row["additions_count"]) >= 0 for row in diffs))
        self.assertTrue(all(int(row["removals_count"]) >= 0 for row in diffs))


if __name__ == "__main__":
    unittest.main()
