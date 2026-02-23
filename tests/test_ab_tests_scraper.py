from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import requests

from init_db import init_database
from scrapers.ab_tests import AB_FRAMEWORK_SIGNATURES, REQUEST_TIMEOUT_SECONDS, detect_frameworks, scrape_ab_tests


class MockResponse:
    def __init__(self, text: str, status_code: int = 200) -> None:
        self.text = text
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")


class ABTestsScraperTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp_dir.name) / "test_competitor_data.db"
        init_database(self.db_path)

    def tearDown(self) -> None:
        self.tmp_dir.cleanup()

    def test_detect_frameworks_finds_multiple_signatures(self) -> None:
        html = """
        <html>
          <head>
            <script src=\"https://cdn.optimizely.com/js/123.js\"></script>
            <script src=\"https://dev.visualwebsiteoptimizer.com/j.php\"></script>
            <script>window.ldclient={};</script>
            <script src=\"https://www.googleoptimize.com/optimize.js?id=OPT-123\"></script>
            <script src=\"https://cdn.split.io/sdk/split-10.0.0.min.js\"></script>
            <script src=\"https://cdn-4.convertexperiments.com/js/1000-10000.js\"></script>
          </head>
        </html>
        """

        detections = detect_frameworks(html)
        detected_names = {tool_name for tool_name, _ in detections}

        self.assertGreaterEqual(len(AB_FRAMEWORK_SIGNATURES), 6)
        self.assertIn("optimizely", detected_names)
        self.assertIn("vwo", detected_names)
        self.assertIn("launchdarkly", detected_names)
        self.assertIn("google_optimize", detected_names)
        self.assertIn("split", detected_names)
        self.assertIn("convert", detected_names)

    def test_scrape_ab_tests_persists_detected_frameworks(self) -> None:
        def fake_get(url: str, timeout: int) -> MockResponse:
            self.assertEqual(timeout, REQUEST_TIMEOUT_SECONDS)
            if "onwardticket.com" in url and "bestonwardticket.com" not in url:
                return MockResponse('<script src="https://cdn.optimizely.com/js/site.js"></script>')
            if "bestonwardticket.com" in url:
                return MockResponse('<script src="https://dev.visualwebsiteoptimizer.com/lib.js"></script>')
            if "dummyticket.com" in url:
                return MockResponse("<html><body>no framework</body></html>")
            if "dummy-tickets.com" in url:
                raise requests.Timeout("timed out")
            if "vizafly.com" in url:
                return MockResponse('<script>window.ldclient = { key: "abc" }</script>')
            return MockResponse("<html></html>")

        with patch("requests.Session.get", side_effect=fake_get), patch("scrapers.ab_tests.datetime") as mock_datetime:
            from datetime import UTC, datetime

            mock_datetime.now.return_value = datetime(2026, 2, 23, 0, 0, tzinfo=UTC)
            success = scrape_ab_tests(self.db_path)

        self.assertTrue(success)

        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT competitor_id, scrape_date, page_url, tool_name, detected, evidence FROM ab_tests ORDER BY id"
            ).fetchall()

        self.assertGreaterEqual(len(rows), 3)
        self.assertTrue(all(int(row["detected"]) == 1 for row in rows))
        self.assertTrue(all(row["scrape_date"] == "2026-02-23" for row in rows))
        self.assertTrue(all(str(row["page_url"]).startswith("https://") for row in rows))
        self.assertTrue(all(row["evidence"] for row in rows))
        self.assertIn("optimizely", {row["tool_name"] for row in rows})
        self.assertIn("vwo", {row["tool_name"] for row in rows})
        self.assertIn("launchdarkly", {row["tool_name"] for row in rows})


if __name__ == "__main__":
    unittest.main()
