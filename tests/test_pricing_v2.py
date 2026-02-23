"""Tests for the v2 pricing scraper (scrapers/pricing.py rewrite)."""
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
    AddonItem,
    PriceV2Record,
    _extract_addons_from_text,
    _extract_from_next_data,
    _is_noise_text,
    extract_pricing_v2,
    scrape_pricing,
)


# ---------------------------------------------------------------------------
# Shared mock helpers
# ---------------------------------------------------------------------------


class MockResponse:
    def __init__(self, text: str, status_code: int = 200) -> None:
        self.text = text
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")


# ---------------------------------------------------------------------------
# Unit: noise detection
# ---------------------------------------------------------------------------


class NoiseDetectionTests(unittest.TestCase):
    def test_js_blob_is_noise(self) -> None:
        self.assertTrue(_is_noise_text('self.__next_f.push([1,"$16"])'))

    def test_cdata_is_noise(self) -> None:
        self.assertTrue(_is_noise_text("<![CDATA[ $16 ]]>"))

    def test_jquery_is_noise(self) -> None:
        self.assertTrue(_is_noise_text("jQuery(document).ready(function() { $16 })"))

    def test_long_text_is_noise(self) -> None:
        self.assertTrue(_is_noise_text("$16 " * 80))

    def test_clean_price_text_not_noise(self) -> None:
        self.assertFalse(_is_noise_text("Starting at just $16"))

    def test_short_hero_text_not_noise(self) -> None:
        self.assertFalse(_is_noise_text("from only $14"))


# ---------------------------------------------------------------------------
# Unit: addon extraction
# ---------------------------------------------------------------------------


class AddonExtractionTests(unittest.TestCase):
    def test_round_trip_addon(self) -> None:
        addons = _extract_addons_from_text("Round Trip (+$7)")
        self.assertEqual(len(addons), 1)
        self.assertEqual(addons[0].name, "Round Trip")
        self.assertAlmostEqual(addons[0].price, 7.0)

    def test_extended_validity_addon(self) -> None:
        addons = _extract_addons_from_text("14 days (+$10)")
        self.assertEqual(len(addons), 1)
        self.assertEqual(addons[0].name, "14 days")
        self.assertAlmostEqual(addons[0].price, 10.0)

    def test_delayed_delivery_addon(self) -> None:
        text = "I want to receive my ticket later(+$1.00 - No delays, served 24/7)"
        addons = _extract_addons_from_text(text)
        self.assertGreaterEqual(len(addons), 1)
        self.assertAlmostEqual(addons[0].price, 1.0)

    def test_multiple_addons_in_one_text(self) -> None:
        text = "Round Trip (+$7) and 7 days (+$7) and 14 days (+$10)"
        addons = _extract_addons_from_text(text)
        self.assertGreaterEqual(len(addons), 2)
        prices = {a.price for a in addons}
        self.assertIn(7.0, prices)
        self.assertIn(10.0, prices)

    def test_no_addon_in_plain_price_text(self) -> None:
        addons = _extract_addons_from_text("Starting at just $16")
        self.assertEqual(addons, [])


# ---------------------------------------------------------------------------
# Unit: __NEXT_DATA__ extraction
# ---------------------------------------------------------------------------

_NEXT_DATA_HTML_TEMPLATE = """
<html><body>
<script id="__NEXT_DATA__" type="application/json">{json_blob}</script>
</body></html>
"""


class NextDataExtractionTests(unittest.TestCase):
    def _html(self, data: object) -> str:
        return _NEXT_DATA_HTML_TEMPLATE.format(json_blob=json.dumps(data))

    def test_extracts_main_price_from_next_data(self) -> None:
        data = {"props": {"pageProps": {"price": "$16 per booking"}}}
        main_price, addons, currency = _extract_from_next_data(self._html(data))
        self.assertAlmostEqual(main_price, 16.0)  # type: ignore[arg-type]
        self.assertEqual(currency, "USD")

    def test_returns_none_when_no_price_in_next_data(self) -> None:
        data = {"props": {"pageProps": {"title": "Onward Ticket"}}}
        main_price, addons, currency = _extract_from_next_data(self._html(data))
        self.assertIsNone(main_price)
        self.assertEqual(addons, [])

    def test_returns_none_for_html_without_next_data_tag(self) -> None:
        html = "<html><body><p>$16</p></body></html>"
        main_price, addons, currency = _extract_from_next_data(html)
        self.assertIsNone(main_price)

    def test_returns_none_for_invalid_json_in_next_data(self) -> None:
        html = '<html><body><script id="__NEXT_DATA__">not json</script></body></html>'
        main_price, addons, currency = _extract_from_next_data(html)
        self.assertIsNone(main_price)

    def test_main_price_is_minimum_found(self) -> None:
        # Two prices in JSON: main should be the smaller one
        data = {"prices": {"base": "$16", "extended": "$26"}}
        main_price, addons, currency = _extract_from_next_data(self._html(data))
        self.assertAlmostEqual(main_price, 16.0)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Unit: extract_pricing_v2 pure function
# ---------------------------------------------------------------------------


class ExtractPricingV2Tests(unittest.TestCase):
    def _call(self, html: str, url: str = "https://example.com") -> PriceV2Record | None:
        return extract_pricing_v2(
            competitor_id=1,
            html=html,
            source_url=url,
            scrape_date="2026-02-23",
            scraped_at="2026-02-23T12:00:00+00:00",
        )

    def test_extracts_main_price_from_hero_text(self) -> None:
        html = "<html><body><h1>Book your onward ticket from just $16</h1></body></html>"
        record = self._call(html)
        self.assertIsNotNone(record)
        assert record is not None
        self.assertAlmostEqual(record.main_price, 16.0)  # type: ignore[arg-type]
        self.assertEqual(record.currency, "USD")

    def test_picks_lowest_price_as_main(self) -> None:
        html = """
        <html><body>
          <p>from only $14</p>
          <p>Round Trip $21</p>
        </body></html>
        """
        record = self._call(html)
        self.assertIsNotNone(record)
        assert record is not None
        self.assertAlmostEqual(record.main_price, 14.0)  # type: ignore[arg-type]

    def test_extracts_addons(self) -> None:
        html = """
        <html><body>
          <p>for only $14</p>
          <p>Round Trip (+$7)</p>
          <p>14 days (+$10)</p>
        </body></html>
        """
        record = self._call(html)
        self.assertIsNotNone(record)
        assert record is not None
        self.assertAlmostEqual(record.main_price, 14.0)  # type: ignore[arg-type]
        addon_prices = {a.price for a in record.addons}
        self.assertIn(7.0, addon_prices)
        self.assertIn(10.0, addon_prices)

    def test_returns_none_when_no_price_in_html(self) -> None:
        html = "<html><body><p>Book your onward ticket today</p></body></html>"
        record = self._call(html)
        self.assertIsNone(record)

    def test_skips_js_noise_text_nodes(self) -> None:
        html = """
        <html><body>
          <script>self.__next_f.push([1,"$16"])</script>
          <p>from only $14</p>
        </body></html>
        """
        record = self._call(html)
        self.assertIsNotNone(record)
        assert record is not None
        self.assertAlmostEqual(record.main_price, 14.0)  # type: ignore[arg-type]

    def test_source_url_stored_in_record(self) -> None:
        html = "<html><body><p>$16</p></body></html>"
        record = self._call(html, url="https://onwardticket.com/pricing")
        self.assertIsNotNone(record)
        assert record is not None
        self.assertEqual(record.source_url, "https://onwardticket.com/pricing")

    def test_competitor_id_stored_in_record(self) -> None:
        html = "<html><body><p>$16</p></body></html>"
        record = self._call(html)
        self.assertIsNotNone(record)
        assert record is not None
        self.assertEqual(record.competitor_id, 1)

    def test_eur_currency_extraction(self) -> None:
        html = "<html><body><p>Starting at €12</p></body></html>"
        record = self._call(html)
        self.assertIsNotNone(record)
        assert record is not None
        self.assertAlmostEqual(record.main_price, 12.0)  # type: ignore[arg-type]
        self.assertEqual(record.currency, "EUR")


# ---------------------------------------------------------------------------
# Integration: scrape_pricing with mocked HTTP
# ---------------------------------------------------------------------------


class ScrapePricingIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp_dir.name) / "test.db"
        init_database(self.db_path)

    def tearDown(self) -> None:
        self.tmp_dir.cleanup()

    def _onwardticket_html(self) -> str:
        return """
        <html><body>
          <h1>Book your onward ticket from just $16</h1>
          <p>Instant & secure booking from just $16</p>
        </body></html>
        """

    def _bestonwardticket_html(self) -> str:
        return """
        <html><body>
          <p>for only $14</p>
          <p>Round Trip (+$7)</p>
          <p>$14.00</p>
          <p>7 days (+$7)</p>
          <p>14 days (+$10)</p>
          <p>I want to receive my ticket later(+$1.00 - No delays, served 24/7)</p>
        </body></html>
        """

    def test_one_row_per_competitor_per_day(self) -> None:
        """prices_v2 must have exactly 1 row per competitor per scrape_date."""
        def fake_get(url: str, timeout: int) -> MockResponse:
            if "onwardticket.com" in url and "best" not in url:
                return MockResponse(self._onwardticket_html())
            if "bestonwardticket.com" in url:
                return MockResponse(self._bestonwardticket_html())
            return MockResponse("<p>from $10</p>")

        with patch("requests.Session.get", side_effect=fake_get):
            result = scrape_pricing(self.db_path)

        self.assertTrue(result)

        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT competitor_id, scrape_date, main_price FROM prices_v2"
            ).fetchall()

        # One row per competitor per date
        seen_pairs: set[tuple[int, str]] = set()
        for row in rows:
            pair = (int(row["competitor_id"]), str(row["scrape_date"]))
            self.assertNotIn(pair, seen_pairs, "Duplicate (competitor_id, scrape_date) in prices_v2")
            seen_pairs.add(pair)

    def test_main_price_populated_for_onwardticket(self) -> None:
        def fake_get(url: str, timeout: int) -> MockResponse:
            if "onwardticket.com" in url and "best" not in url:
                return MockResponse(self._onwardticket_html())
            return MockResponse("<p>$10</p>")

        with patch("requests.Session.get", side_effect=fake_get):
            scrape_pricing(self.db_path)

        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT main_price FROM prices_v2 WHERE competitor_id = "
                "(SELECT id FROM competitors WHERE domain = 'onwardticket.com')"
            ).fetchall()

        self.assertGreaterEqual(len(rows), 1)
        self.assertAlmostEqual(float(rows[0]["main_price"]), 16.0)

    def test_main_price_populated_for_bestonwardticket(self) -> None:
        def fake_get(url: str, timeout: int) -> MockResponse:
            if "bestonwardticket.com" in url:
                return MockResponse(self._bestonwardticket_html())
            return MockResponse("<p>$10</p>")

        with patch("requests.Session.get", side_effect=fake_get):
            scrape_pricing(self.db_path)

        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT main_price, addons FROM prices_v2 WHERE competitor_id = "
                "(SELECT id FROM competitors WHERE domain = 'bestonwardticket.com')"
            ).fetchall()

        self.assertGreaterEqual(len(rows), 1)
        self.assertAlmostEqual(float(rows[0]["main_price"]), 14.0)

    def test_addons_stored_as_valid_json(self) -> None:
        def fake_get(url: str, timeout: int) -> MockResponse:
            if "bestonwardticket.com" in url:
                return MockResponse(self._bestonwardticket_html())
            return MockResponse("<p>$10</p>")

        with patch("requests.Session.get", side_effect=fake_get):
            scrape_pricing(self.db_path)

        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT addons FROM prices_v2 WHERE competitor_id = "
                "(SELECT id FROM competitors WHERE domain = 'bestonwardticket.com')"
            ).fetchall()

        self.assertGreaterEqual(len(rows), 1)
        addons_raw = rows[0]["addons"]
        self.assertIsNotNone(addons_raw)
        parsed = json.loads(addons_raw)
        self.assertIsInstance(parsed, list)
        self.assertGreater(len(parsed), 0)
        # Each addon has name and price
        for addon in parsed:
            self.assertIn("name", addon)
            self.assertIn("price", addon)

    def test_no_js_noise_rows(self) -> None:
        """prices_v2 must not contain rows whose main_price came from JS noise."""
        noise_html = """
        <html><body>
          <script>self.__next_f.push([1,"$16 booking"])</script>
          <p>jQuery(document).ready(function() { $16 })</p>
        </body></html>
        """

        def fake_get(url: str, timeout: int) -> MockResponse:
            return MockResponse(noise_html)

        with patch("requests.Session.get", side_effect=fake_get):
            scrape_pricing(self.db_path)

        # If noise filtering works, either no rows or rows with NULL main_price
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT main_price FROM prices_v2"
            ).fetchall()

        for row in rows:
            # If a row was inserted, main_price must not be from a JS noise source.
            # Since noise HTML has no clean price text, main_price should be NULL.
            self.assertIsNone(row[0], "Row with JS-noise-derived main_price found in prices_v2")

    def test_scrape_continues_on_timeout(self) -> None:
        """Timeout for one competitor must not crash; others still processed."""
        def fake_get(url: str, timeout: int) -> MockResponse:
            if "bestonwardticket.com" in url:
                raise requests.Timeout("timed out")
            return MockResponse("<p>from $10</p>")

        with patch("requests.Session.get", side_effect=fake_get):
            result = scrape_pricing(self.db_path)

        # Should still return True (other competitors succeeded)
        self.assertTrue(result)

    def test_scrape_continues_on_http_error(self) -> None:
        """HTTP 500 for one competitor must not crash; others still processed."""
        def fake_get(url: str, timeout: int) -> MockResponse:
            if "dummyticket.com" in url:
                return MockResponse("error", status_code=500)
            return MockResponse("<p>from $10</p>")

        with patch("requests.Session.get", side_effect=fake_get):
            result = scrape_pricing(self.db_path)

        self.assertTrue(result)

    def test_idempotent_second_scrape_same_day(self) -> None:
        """Running scrape twice on same day should replace, not duplicate, the row."""
        def fake_get(url: str, timeout: int) -> MockResponse:
            return MockResponse("<p>from $10</p>")

        with patch("requests.Session.get", side_effect=fake_get):
            scrape_pricing(self.db_path)
            scrape_pricing(self.db_path)

        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT competitor_id, scrape_date, COUNT(*) as cnt FROM prices_v2 "
                "GROUP BY competitor_id, scrape_date HAVING cnt > 1"
            ).fetchall()

        self.assertEqual(len(rows), 0, "Duplicate (competitor_id, scrape_date) rows found after two scrapes")

    def test_scrape_returns_false_when_all_fail(self) -> None:
        def fake_get(url: str, timeout: int) -> MockResponse:
            raise requests.Timeout("timed out")

        with patch("requests.Session.get", side_effect=fake_get):
            result = scrape_pricing(self.db_path)

        self.assertFalse(result)

    def test_next_data_site_extraction(self) -> None:
        """Next.js site with __NEXT_DATA__ containing $16 should store main_price=16."""
        next_data_html = """
        <html><body>
          <script id="__NEXT_DATA__" type="application/json">
            {"props": {"pageProps": {"heroText": "Book from $16 now"}}}
          </script>
        </body></html>
        """

        def fake_get(url: str, timeout: int) -> MockResponse:
            if "onwardticket.com" in url and "best" not in url:
                return MockResponse(next_data_html)
            return MockResponse("<p>$10</p>")

        with patch("requests.Session.get", side_effect=fake_get):
            scrape_pricing(self.db_path)

        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT main_price FROM prices_v2 WHERE competitor_id = "
                "(SELECT id FROM competitors WHERE domain = 'onwardticket.com')"
            ).fetchall()

        self.assertGreaterEqual(len(rows), 1)
        self.assertAlmostEqual(float(rows[0]["main_price"]), 16.0)

    def test_addons_null_when_no_addons(self) -> None:
        """When no addons present, addons column should be NULL."""
        def fake_get(url: str, timeout: int) -> MockResponse:
            return MockResponse("<p>from $16</p>")

        with patch("requests.Session.get", side_effect=fake_get):
            scrape_pricing(self.db_path)

        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT addons FROM prices_v2 WHERE competitor_id = "
                "(SELECT id FROM competitors WHERE domain = 'onwardticket.com')"
            ).fetchall()

        self.assertGreaterEqual(len(rows), 1)
        self.assertIsNone(rows[0][0])

    def test_source_url_stored(self) -> None:
        """source_url should be populated with the URL that yielded the price."""
        def fake_get(url: str, timeout: int) -> MockResponse:
            return MockResponse("<p>from $16</p>")

        with patch("requests.Session.get", side_effect=fake_get):
            scrape_pricing(self.db_path)

        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT source_url FROM prices_v2 WHERE main_price IS NOT NULL"
            ).fetchall()

        self.assertGreater(len(rows), 0)
        for row in rows:
            self.assertIsNotNone(row[0])
            self.assertTrue(str(row[0]).startswith("http"))


if __name__ == "__main__":
    unittest.main()
