from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import requests

from init_db import init_database
from scrapers.products import REQUEST_TIMEOUT_SECONDS, extract_product_records, scrape_products


class MockResponse:
    def __init__(self, text: str, status_code: int = 200) -> None:
        self.text = text
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")


class ProductScraperTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp_dir.name) / "test_competitor_data.db"
        init_database(self.db_path)

    def tearDown(self) -> None:
        self.tmp_dir.cleanup()

    def test_extract_product_records_parses_service_and_price_range(self) -> None:
        html = """
        <section>
          <h2>Onward Ticket Service</h2>
          <p>Instant onward reservation from $12 to $18 for visa processing.</p>
        </section>
        """

        records = extract_product_records(
            competitor_id=1,
            html=html,
            source_url="https://example.com/products",
            scrape_date="2026-02-22",
            scraped_at="2026-02-22T23:00:00+00:00",
        )

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].product_name, "Onward Ticket Service")
        self.assertEqual(records[0].price_range, "12.00-18.00")
        self.assertIn("visa processing", records[0].description or "")
        self.assertEqual(records[0].url, "https://example.com/products")

    def test_scrape_products_persists_rows_and_detects_new_products(self) -> None:
        calls: list[tuple[str, int]] = []

        def fake_get_first(url: str, timeout: int) -> MockResponse:
            calls.append((url, timeout))
            if "bestonwardticket.com" in url:
                raise requests.Timeout("timed out")
            if "dummyticket.com" in url:
                return MockResponse("down", status_code=503)
            return MockResponse("<section><h3>Single Ticket</h3><p>$14</p></section>")

        with patch("requests.Session.get", side_effect=fake_get_first):
            first_success = scrape_products(self.db_path)

        self.assertTrue(first_success)
        self.assertTrue(calls)
        self.assertTrue(all(timeout == REQUEST_TIMEOUT_SECONDS for _, timeout in calls))

        def fake_get_second(url: str, timeout: int) -> MockResponse:
            if "bestonwardticket.com" in url:
                return MockResponse("<section><h3>Single Ticket</h3><p>$14</p></section>")
            if "onwardticket.com" in url:
                return MockResponse(
                    "<section><h3>Single Ticket</h3><p>$14</p></section>"
                    "<section><h3>Round Trip Ticket</h3><p>$21</p></section>"
                )
            return MockResponse("<section><h3>Single Ticket</h3><p>$14</p></section>")

        with patch("requests.Session.get", side_effect=fake_get_second), patch(
            "scrapers.products.datetime"
        ) as mock_datetime:
            from datetime import UTC, datetime

            mock_datetime.now.return_value = datetime(2026, 2, 23, 9, 0, tzinfo=UTC)
            second_success = scrape_products(self.db_path)

        self.assertTrue(second_success)

        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT competitor_id, product_name, description, price_range, url, scraped_at FROM products"
            ).fetchall()
            second_day_new = conn.execute(
                """
                SELECT COUNT(*)
                FROM products
                WHERE scrape_date = '2026-02-23' AND product_name = 'Round Trip Ticket'
                """
            ).fetchone()[0]

        self.assertGreaterEqual(len(rows), 1)
        self.assertEqual(second_day_new, 1)

        for row in rows:
            self.assertIsNotNone(row["competitor_id"])
            self.assertTrue(row["product_name"])
            self.assertIsNotNone(row["description"])
            self.assertIsNotNone(row["url"])
            self.assertIsNotNone(row["scraped_at"])


if __name__ == "__main__":
    unittest.main()
