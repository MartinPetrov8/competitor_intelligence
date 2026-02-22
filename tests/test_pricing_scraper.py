from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import requests

from init_db import init_database
from scrapers.pricing import REQUEST_TIMEOUT_SECONDS, extract_price_records, scrape_pricing


class MockResponse:
    def __init__(self, text: str, status_code: int = 200) -> None:
        self.text = text
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")


class PricingScraperTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp_dir.name) / "test_competitor_data.db"
        init_database(self.db_path)

    def tearDown(self) -> None:
        self.tmp_dir.cleanup()

    def test_extract_price_records_parses_product_name_price_and_currency(self) -> None:
        html = """
        <section>
          <h2>One Way Ticket</h2>
          <p>From $12.99 per booking</p>
        </section>
        """
        records = extract_price_records(
            competitor_id=1,
            html=html,
            source_url="https://example.com/pricing",
            scrape_date="2026-02-22",
            scraped_at="2026-02-22T23:00:00+00:00",
        )

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].product_name, "One Way Ticket")
        self.assertEqual(records[0].currency, "USD")
        self.assertAlmostEqual(records[0].price_usd, 12.99)
        self.assertIn("$12.99", records[0].raw_text)

    def test_scrape_pricing_continues_on_timeout_and_http_errors(self) -> None:
        calls: list[tuple[str, int]] = []

        def fake_get(url: str, timeout: int) -> MockResponse:
            calls.append((url, timeout))
            if "onwardticket.com" in url and url.endswith("/pricing"):
                return MockResponse("<h2>Starter</h2><p>$10</p>")
            if "bestonwardticket.com" in url:
                raise requests.Timeout("timed out")
            if "dummyticket.com" in url:
                return MockResponse("server down", status_code=500)
            return MockResponse("<h3>Standard</h3><p>$15</p>")

        with patch("requests.Session.get", side_effect=fake_get):
            success = scrape_pricing(self.db_path)

        self.assertTrue(success)
        self.assertTrue(calls)
        self.assertTrue(all(timeout == REQUEST_TIMEOUT_SECONDS for _, timeout in calls))

        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT competitor_id, product_name, price_usd, currency, bundle_info, scraped_at FROM prices"
            ).fetchall()

        self.assertGreaterEqual(len(rows), 1)
        for row in rows:
            self.assertIsNotNone(row["competitor_id"])
            self.assertTrue(row["product_name"])
            self.assertIsNotNone(row["price_usd"])
            self.assertTrue(row["currency"])
            self.assertIsNotNone(row["scraped_at"])


if __name__ == "__main__":
    unittest.main()
