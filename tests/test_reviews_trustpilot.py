from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import requests

from init_db import init_database
from scrapers.reviews_trustpilot import (
    REQUEST_TIMEOUT_SECONDS,
    extract_trustpilot_review_record,
    scrape_reviews_trustpilot,
)


class MockResponse:
    def __init__(self, text: str, status_code: int = 200) -> None:
        self.text = text
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")


class TrustpilotScraperTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp_dir.name) / "test_competitor_data.db"
        init_database(self.db_path)

    def tearDown(self) -> None:
        self.tmp_dir.cleanup()

    def test_extract_trustpilot_review_record_from_ld_json_and_distribution(self) -> None:
        html = """
        <html><head>
          <script type=\"application/ld+json\">
            {
              \"@context\": \"https://schema.org\",
              \"@type\": \"Organization\",
              \"aggregateRating\": {
                \"@type\": \"AggregateRating\",
                \"ratingValue\": \"4.6\",
                \"reviewCount\": \"1234\"
              }
            }
          </script>
          <script>
            window.__DATA__ = {
              \"stars\": \"5\", \"count\": 1000,
              \"stars\": \"4\", \"count\": 120,
              \"stars\": \"3\", \"count\": 60,
              \"stars\": \"2\", \"count\": 30,
              \"stars\": \"1\", \"count\": 24
            };
          </script>
        </head><body></body></html>
        """

        record = extract_trustpilot_review_record(
            competitor_id=1,
            html=html,
            source_url="https://www.trustpilot.com/review/example.com",
            scrape_date="2026-02-22",
            scraped_at="2026-02-22T23:00:00+00:00",
        )

        self.assertIsNotNone(record)
        assert record is not None
        self.assertEqual(record.overall_rating, 4.6)
        self.assertEqual(record.review_count, 1234)
        self.assertEqual(record.stars_5, 1000)
        self.assertEqual(record.stars_4, 120)
        self.assertEqual(record.stars_3, 60)
        self.assertEqual(record.stars_2, 30)
        self.assertEqual(record.stars_1, 24)

    def test_scrape_reviews_trustpilot_continues_on_missing_pages_and_stores_reachable(self) -> None:
        calls: list[tuple[str, int]] = []

        def fake_get(url: str, timeout: int) -> MockResponse:
            calls.append((url, timeout))
            if "bestonwardticket.com" in url:
                return MockResponse("missing", status_code=404)
            if "dummy-tickets.com" in url:
                raise requests.Timeout("timed out")
            return MockResponse(
                """
                <script type=\"application/ld+json\">
                {"aggregateRating": {"ratingValue": "4.1", "reviewCount": "250"}}
                </script>
                <script>
                {"stars":"5","count":150,"stars":"4","count":50,"stars":"3","count":25,"stars":"2","count":15,"stars":"1","count":10}
                </script>
                """
            )

        with patch("requests.Session.get", side_effect=fake_get):
            success = scrape_reviews_trustpilot(self.db_path)

        self.assertTrue(success)
        self.assertTrue(calls)
        self.assertTrue(all(timeout == REQUEST_TIMEOUT_SECONDS for _, timeout in calls))

        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT competitor_id, overall_rating, total_reviews, review_count,
                       stars_5, stars_4, stars_3, stars_2, stars_1, scraped_at
                FROM reviews_trustpilot
                ORDER BY id
                """
            ).fetchall()

        self.assertEqual(len(rows), 3)
        for row in rows:
            self.assertEqual(row["overall_rating"], 4.1)
            self.assertEqual(row["total_reviews"], 250)
            self.assertEqual(row["review_count"], 250)
            self.assertEqual(row["stars_5"], 150)
            self.assertEqual(row["stars_1"], 10)
            self.assertIsNotNone(row["scraped_at"])


if __name__ == "__main__":
    unittest.main()
