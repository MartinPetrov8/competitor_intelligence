"""Legacy pricing scraper tests — updated for v2 API (pricing.py rewrite).

The v2 rewrite replaced extract_price_records() with extract_pricing_v2() and
scrapes into prices_v2 (one row per competitor per day). These tests have been
updated to use the new API while preserving all behavioural coverage.
"""
from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import requests

from init_db import init_database
from scrapers.pricing import (
    REQUEST_TIMEOUT_SECONDS,
    _is_noise_text,
    extract_pricing_v2,
    scrape_pricing,
)


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

    def test_extract_pricing_v2_parses_main_price_and_currency(self) -> None:
        html = """
        <section>
          <h2>One Way Ticket</h2>
          <p>From $12.99 per booking</p>
        </section>
        """
        record = extract_pricing_v2(
            competitor_id=1,
            html=html,
            source_url="https://example.com/pricing",
            scrape_date="2026-02-22",
            scraped_at="2026-02-22T23:00:00+00:00",
        )

        self.assertIsNotNone(record)
        assert record is not None
        self.assertEqual(record.currency, "USD")
        self.assertAlmostEqual(record.main_price, 12.99)  # type: ignore[arg-type]
        self.assertEqual(record.competitor_id, 1)

    def test_scrape_pricing_continues_on_timeout_and_http_errors(self) -> None:
        calls: list[tuple[str, int]] = []

        def fake_get(url: str, timeout: int) -> MockResponse:
            calls.append((url, timeout))
            if "onwardticket.com" in url and "best" not in url and url.endswith("/pricing"):
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
                "SELECT competitor_id, main_price, currency, scraped_at FROM prices_v2"
            ).fetchall()

        self.assertGreaterEqual(len(rows), 1)
        for row in rows:
            self.assertIsNotNone(row["competitor_id"])
            self.assertIsNotNone(row["main_price"])
            self.assertTrue(row["currency"])
            self.assertIsNotNone(row["scraped_at"])

    def test_extract_pricing_v2_skips_js_noise_in_raw_text(self) -> None:
        """Regression test: pricing scraper must not store JS code blocks as price records.

        Previously the scraper extracted any text matching the price pattern, including
        Next.js serialized JS blobs like self.__next_f.push([...,"$12"...]) and
        long HTML strings, resulting in JS noise in DB rows.
        The fix adds _is_noise_text filtering.
        """
        js_blob = 'self.__next_f.push([1,"<div class=\\"price\\">$9.99</div>"])' + " x" * 250
        clean_html = f"""
        <html><body>
          <section>
            <h2>Basic Plan</h2>
            <p>Only $9.99 per month</p>
          </section>
          <script>{js_blob}</script>
          <script>jQuery(document).ready(function(){{ var p = "$15.00"; }});</script>
        </body></html>
        """
        record = extract_pricing_v2(
            competitor_id=3,
            html=clean_html,
            source_url="https://example.com/pricing",
            scrape_date="2026-02-23",
            scraped_at="2026-02-23T09:00:00+00:00",
        )

        # The clean price should be extracted
        self.assertIsNotNone(record)
        assert record is not None
        self.assertAlmostEqual(record.main_price, 9.99)  # type: ignore[arg-type]
        # Verify the noise text would have been filtered
        self.assertTrue(_is_noise_text(js_blob), "JS blob should be detected as noise")
        self.assertFalse(_is_noise_text("Only $9.99 per month"), "Clean text should not be detected as noise")

    def test_is_noise_text_detects_known_js_patterns(self) -> None:
        """Unit test for _is_noise_text helper — covers all known JS/HTML noise indicators."""
        # Should detect as noise
        self.assertTrue(_is_noise_text('self.__next_f.push([1,"hello $5"])'))
        self.assertTrue(_is_noise_text("/* <![CDATA[ */ var price = '$10'; /* ]]> */"))
        self.assertTrue(_is_noise_text("gform.initializeOnLoaded(function(){ return $20; })"))
        self.assertTrue(_is_noise_text("jQuery(document).ready(function(){ })"))
        self.assertTrue(_is_noise_text("window.__NEXT_DATA__ = {price: '$5'}"))
        self.assertTrue(_is_noise_text("function(x){ return x * $3; }"))
        self.assertTrue(_is_noise_text("a" * 501))  # Too long
        # Should NOT detect as noise
        self.assertFalse(_is_noise_text("$12.99 per booking"))
        self.assertFalse(_is_noise_text("From £9 for a one-way ticket"))
        self.assertFalse(_is_noise_text(""))


if __name__ == "__main__":
    unittest.main()
