from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import requests

from init_db import init_database
from scrapers.reviews_google import (
    REQUEST_TIMEOUT_SECONDS,
    extract_google_review_record,
    scrape_reviews_google,
)


class MockResponse:
    def __init__(self, text: str, status_code: int = 200) -> None:
        self.text = text
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")


class GoogleReviewsScraperTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp_dir.name) / "test_competitor_data.db"
        init_database(self.db_path)

    def tearDown(self) -> None:
        self.tmp_dir.cleanup()

    def test_extract_google_review_record_from_ld_json(self) -> None:
        html = """
        <html><head>
          <script type="application/ld+json">
            {
              "@type": "LocalBusiness",
              "aggregateRating": {
                "@type": "AggregateRating",
                "ratingValue": "4.7",
                "reviewCount": "321"
              }
            }
          </script>
        </head><body></body></html>
        """

        record = extract_google_review_record(
            competitor_id=1,
            html=html,
            source_url="https://www.google.com/search?q=onwardticket.com",
            scrape_date="2026-02-23",
            scraped_at="2026-02-23T00:00:00+00:00",
        )

        self.assertIsNotNone(record)
        assert record is not None
        self.assertEqual(record.overall_rating, 4.7)
        self.assertEqual(record.review_count, 321)

    def test_scrape_reviews_google_continues_on_missing_pages_and_stores_reachable(self) -> None:
        calls: list[tuple[str, int]] = []

        def fake_get(url: str, timeout: int, headers: dict[str, str]) -> MockResponse:
            calls.append((url, timeout))
            if "bestonwardticket.com" in url:
                return MockResponse("missing", status_code=404)
            if "dummy-tickets.com" in url:
                raise requests.Timeout("timed out")
            return MockResponse(
                """
                <script type="application/ld+json">
                  {"aggregateRating": {"ratingValue": "4.2", "reviewCount": "180"}}
                </script>
                """
            )

        with patch("requests.Session.get", side_effect=fake_get):
            success = scrape_reviews_google(self.db_path)

        self.assertTrue(success)
        self.assertTrue(calls)
        self.assertTrue(all(timeout == REQUEST_TIMEOUT_SECONDS for _, timeout in calls))

        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT competitor_id, overall_rating, total_reviews, review_count, scraped_at
                FROM reviews_google
                ORDER BY id
                """
            ).fetchall()

        self.assertEqual(len(rows), 3)
        for row in rows:
            self.assertEqual(row["overall_rating"], 4.2)
            self.assertEqual(row["total_reviews"], 180)
            self.assertEqual(row["review_count"], 180)
            self.assertIsNotNone(row["scraped_at"])


if __name__ == "__main__":
    unittest.main()
