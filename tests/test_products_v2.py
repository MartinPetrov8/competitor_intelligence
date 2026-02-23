"""Tests for the v2 products scraper (scrapers/products.py rewrite)."""
from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import requests

from init_db import init_database
from scrapers.products import (
    ProductV2Record,
    _detect_category,
    _ONE_WAY_KEYWORDS,
    _ROUND_TRIP_KEYWORDS,
    _HOTEL_KEYWORDS,
    _VISA_LETTER_KEYWORDS,
    _page_text,
    extract_products_v2,
    scrape_products,
    _ensure_products_v2_schema,
    _store_product_v2,
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
# Shared HTML fixtures
# ---------------------------------------------------------------------------

_ONE_WAY_HTML = """
<html><body>
  <h1>Onward Ticket Service</h1>
  <p>Get your dummy ticket for just $14. One-way flight reservation for visa applications.</p>
</body></html>
"""

_ROUND_TRIP_HTML = """
<html><body>
  <h1>Round Trip Reservation</h1>
  <p>Book a round trip flight booking for $21 — perfect for return visits.</p>
</body></html>
"""

_HOTEL_HTML = """
<html><body>
  <h2>Hotel Booking</h2>
  <p>Reserve a dummy hotel accommodation from $10 per night.</p>
</body></html>
"""

_VISA_LETTER_HTML = """
<html><body>
  <h2>Visa Support Letter</h2>
  <p>Official invitation letter for your visa application — only $8.</p>
</body></html>
"""

_ALL_PRODUCTS_HTML = """
<html><body>
  <h1>Our Services</h1>
  <ul>
    <li>One-way onward ticket — $14</li>
    <li>Round trip reservation — $21</li>
    <li>Hotel accommodation booking — $10</li>
    <li>Visa support letter — $8</li>
  </ul>
</body></html>
"""

_NO_PRODUCTS_HTML = """
<html><body>
  <p>Welcome to our website. We sell widgets.</p>
</body></html>
"""


# ---------------------------------------------------------------------------
# Unit: keyword detection
# ---------------------------------------------------------------------------


class KeywordDetectionTests(unittest.TestCase):
    def test_one_way_keyword_detected(self) -> None:
        page = "get your one-way ticket today"
        self.assertTrue(_detect_category(page, _ONE_WAY_KEYWORDS))

    def test_onward_ticket_keyword_detected(self) -> None:
        page = "buy onward ticket for visa"
        self.assertTrue(_detect_category(page, _ONE_WAY_KEYWORDS))

    def test_dummy_ticket_keyword_detected(self) -> None:
        page = "order a dummy ticket now"
        self.assertTrue(_detect_category(page, _ONE_WAY_KEYWORDS))

    def test_flight_reservation_keyword_detected(self) -> None:
        page = "flight reservation for your visa"
        self.assertTrue(_detect_category(page, _ONE_WAY_KEYWORDS))

    def test_round_trip_keyword_detected(self) -> None:
        page = "book your round trip flight"
        self.assertTrue(_detect_category(page, _ROUND_TRIP_KEYWORDS))

    def test_return_keyword_detected(self) -> None:
        page = "return flight booking"
        self.assertTrue(_detect_category(page, _ROUND_TRIP_KEYWORDS))

    def test_hotel_keyword_detected(self) -> None:
        page = "dummy hotel booking for stays"
        self.assertTrue(_detect_category(page, _HOTEL_KEYWORDS))

    def test_accommodation_keyword_detected(self) -> None:
        page = "find accommodation near the airport"
        self.assertTrue(_detect_category(page, _HOTEL_KEYWORDS))

    def test_visa_keyword_detected(self) -> None:
        page = "support visa application with our letter"
        self.assertTrue(_detect_category(page, _VISA_LETTER_KEYWORDS))

    def test_support_letter_keyword_detected(self) -> None:
        page = "we provide an official support letter"
        self.assertTrue(_detect_category(page, _VISA_LETTER_KEYWORDS))

    def test_no_match_returns_false(self) -> None:
        page = "buy widgets and gadgets here"
        self.assertFalse(_detect_category(page, _ONE_WAY_KEYWORDS))
        self.assertFalse(_detect_category(page, _ROUND_TRIP_KEYWORDS))
        self.assertFalse(_detect_category(page, _HOTEL_KEYWORDS))
        self.assertFalse(_detect_category(page, _VISA_LETTER_KEYWORDS))


# ---------------------------------------------------------------------------
# Unit: _page_text
# ---------------------------------------------------------------------------


class PageTextTests(unittest.TestCase):
    def test_strips_html_tags(self) -> None:
        html = "<p>Hello <b>World</b></p>"
        result = _page_text(html)
        self.assertIn("hello", result)
        self.assertIn("world", result)
        self.assertNotIn("<", result)

    def test_lowercases_text(self) -> None:
        html = "<p>ONE-WAY TICKET</p>"
        result = _page_text(html)
        self.assertIn("one-way ticket", result)


# ---------------------------------------------------------------------------
# Unit: extract_products_v2 — pure function
# ---------------------------------------------------------------------------


class ExtractProductsV2Tests(unittest.TestCase):
    def _make_record(self, html_pages: list[tuple[str, str]]) -> ProductV2Record:
        return extract_products_v2(
            competitor_id=1,
            html_pages=html_pages,
            scrape_date="2026-02-23",
            scraped_at="2026-02-23T14:00:00+00:00",
        )

    def test_one_way_detected(self) -> None:
        record = self._make_record([("https://example.com", _ONE_WAY_HTML)])
        self.assertTrue(record.one_way_offered)

    def test_round_trip_detected(self) -> None:
        record = self._make_record([("https://example.com", _ROUND_TRIP_HTML)])
        self.assertTrue(record.round_trip_offered)

    def test_hotel_detected(self) -> None:
        record = self._make_record([("https://example.com", _HOTEL_HTML)])
        self.assertTrue(record.hotel_offered)

    def test_visa_letter_detected(self) -> None:
        record = self._make_record([("https://example.com", _VISA_LETTER_HTML)])
        self.assertTrue(record.visa_letter_offered)

    def test_all_products_detected_in_single_page(self) -> None:
        record = self._make_record([("https://example.com", _ALL_PRODUCTS_HTML)])
        self.assertTrue(record.one_way_offered)
        self.assertTrue(record.round_trip_offered)
        self.assertTrue(record.hotel_offered)
        self.assertTrue(record.visa_letter_offered)

    def test_no_products_all_false(self) -> None:
        record = self._make_record([("https://example.com", _NO_PRODUCTS_HTML)])
        self.assertFalse(record.one_way_offered)
        self.assertFalse(record.round_trip_offered)
        self.assertFalse(record.hotel_offered)
        self.assertFalse(record.visa_letter_offered)

    def test_one_way_false_when_not_present(self) -> None:
        record = self._make_record([("https://example.com", _HOTEL_HTML)])
        self.assertFalse(record.one_way_offered)

    def test_price_extracted_for_one_way(self) -> None:
        record = self._make_record([("https://example.com", _ONE_WAY_HTML)])
        self.assertIsNotNone(record.one_way_price)
        self.assertAlmostEqual(record.one_way_price or 0.0, 14.0)

    def test_price_extracted_for_round_trip(self) -> None:
        record = self._make_record([("https://example.com", _ROUND_TRIP_HTML)])
        self.assertIsNotNone(record.round_trip_price)
        self.assertAlmostEqual(record.round_trip_price or 0.0, 21.0)

    def test_price_extracted_for_hotel(self) -> None:
        record = self._make_record([("https://example.com", _HOTEL_HTML)])
        self.assertIsNotNone(record.hotel_price)
        self.assertAlmostEqual(record.hotel_price or 0.0, 10.0)

    def test_price_extracted_for_visa_letter(self) -> None:
        record = self._make_record([("https://example.com", _VISA_LETTER_HTML)])
        self.assertIsNotNone(record.visa_letter_price)
        self.assertAlmostEqual(record.visa_letter_price or 0.0, 8.0)

    def test_or_merge_across_pages(self) -> None:
        """Boolean flags merge across multiple pages (OR semantics)."""
        record = self._make_record([
            ("https://example.com", _ONE_WAY_HTML),
            ("https://example.com/hotel", _HOTEL_HTML),
        ])
        self.assertTrue(record.one_way_offered)
        self.assertTrue(record.hotel_offered)
        self.assertFalse(record.round_trip_offered)

    def test_competitor_id_preserved(self) -> None:
        record = extract_products_v2(
            competitor_id=42,
            html_pages=[("https://example.com", _ONE_WAY_HTML)],
            scrape_date="2026-02-23",
            scraped_at="2026-02-23T14:00:00+00:00",
        )
        self.assertEqual(record.competitor_id, 42)

    def test_scrape_date_preserved(self) -> None:
        record = self._make_record([("https://example.com", _ONE_WAY_HTML)])
        self.assertEqual(record.scrape_date, "2026-02-23")

    def test_source_url_is_first_page(self) -> None:
        record = self._make_record([
            ("https://first.com", _ONE_WAY_HTML),
            ("https://second.com", _HOTEL_HTML),
        ])
        self.assertEqual(record.source_url, "https://first.com")

    def test_empty_pages_returns_all_false(self) -> None:
        record = self._make_record([])
        self.assertFalse(record.one_way_offered)
        self.assertFalse(record.round_trip_offered)
        self.assertFalse(record.hotel_offered)
        self.assertFalse(record.visa_letter_offered)


# ---------------------------------------------------------------------------
# DB: _ensure_products_v2_schema + _store_product_v2
# ---------------------------------------------------------------------------


class StoreProductV2Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp_dir.name) / "test.db"
        init_database(self.db_path)

    def tearDown(self) -> None:
        self.tmp_dir.cleanup()

    def _open_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _make_record(self, competitor_id: int = 1, scrape_date: str = "2026-02-23") -> ProductV2Record:
        return ProductV2Record(
            competitor_id=competitor_id,
            scrape_date=scrape_date,
            scraped_at="2026-02-23T14:00:00+00:00",
            one_way_offered=True,
            one_way_price=14.0,
            round_trip_offered=True,
            round_trip_price=21.0,
            hotel_offered=False,
            hotel_price=None,
            visa_letter_offered=True,
            visa_letter_price=8.0,
            source_url="https://example.com",
        )

    def test_schema_created_idempotent(self) -> None:
        with self._open_conn() as conn:
            _ensure_products_v2_schema(conn)
            _ensure_products_v2_schema(conn)  # second call must not raise
        # table should exist
        with self._open_conn() as conn:
            cols = {row["name"] for row in conn.execute("PRAGMA table_info(products_v2)").fetchall()}
        self.assertIn("one_way_offered", cols)
        self.assertIn("visa_letter_offered", cols)

    def test_store_inserts_row(self) -> None:
        record = self._make_record()
        with self._open_conn() as conn:
            _ensure_products_v2_schema(conn)
            _store_product_v2(conn, record)
            conn.commit()
        with self._open_conn() as conn:
            rows = conn.execute("SELECT * FROM products_v2").fetchall()
        self.assertEqual(len(rows), 1)

    def test_stored_flags_are_correct(self) -> None:
        record = self._make_record()
        with self._open_conn() as conn:
            _ensure_products_v2_schema(conn)
            _store_product_v2(conn, record)
            conn.commit()
        with self._open_conn() as conn:
            row = conn.execute("SELECT * FROM products_v2").fetchone()
        self.assertEqual(row["one_way_offered"], 1)
        self.assertEqual(row["round_trip_offered"], 1)
        self.assertEqual(row["hotel_offered"], 0)
        self.assertEqual(row["visa_letter_offered"], 1)

    def test_stored_prices_are_correct(self) -> None:
        record = self._make_record()
        with self._open_conn() as conn:
            _ensure_products_v2_schema(conn)
            _store_product_v2(conn, record)
            conn.commit()
        with self._open_conn() as conn:
            row = conn.execute("SELECT * FROM products_v2").fetchone()
        self.assertAlmostEqual(row["one_way_price"], 14.0)
        self.assertAlmostEqual(row["round_trip_price"], 21.0)
        self.assertIsNone(row["hotel_price"])
        self.assertAlmostEqual(row["visa_letter_price"], 8.0)

    def test_unique_constraint_on_replace(self) -> None:
        """Second INSERT OR REPLACE for same competitor/date overwrites, stays 1 row."""
        record1 = self._make_record()
        record2 = ProductV2Record(
            competitor_id=1,
            scrape_date="2026-02-23",
            scraped_at="2026-02-23T15:00:00+00:00",
            one_way_offered=False,
            one_way_price=None,
            round_trip_offered=False,
            round_trip_price=None,
            hotel_offered=True,
            hotel_price=10.0,
            visa_letter_offered=False,
            visa_letter_price=None,
            source_url="https://example.com",
        )
        with self._open_conn() as conn:
            _ensure_products_v2_schema(conn)
            _store_product_v2(conn, record1)
            conn.commit()
            _store_product_v2(conn, record2)
            conn.commit()
        with self._open_conn() as conn:
            rows = conn.execute("SELECT * FROM products_v2").fetchall()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["hotel_offered"], 1)

    def test_different_dates_create_separate_rows(self) -> None:
        r1 = self._make_record(scrape_date="2026-02-22")
        r2 = self._make_record(scrape_date="2026-02-23")
        with self._open_conn() as conn:
            _ensure_products_v2_schema(conn)
            _store_product_v2(conn, r1)
            _store_product_v2(conn, r2)
            conn.commit()
        with self._open_conn() as conn:
            rows = conn.execute("SELECT * FROM products_v2").fetchall()
        self.assertEqual(len(rows), 2)


# ---------------------------------------------------------------------------
# Integration: scrape_products with mocked HTTP
# ---------------------------------------------------------------------------


_HOMEPAGE_HTML = """
<html><body>
  <h1>DummyVisaTicket</h1>
  <p>One-way onward ticket — $14. Flight reservation for visa applications.</p>
  <p>Also offering round trip — $21, hotel booking — $10, visa support letter — $8.</p>
</body></html>
"""

_TIMEOUT_ONLY_HTML = None  # sentinel for timeout competitor


class ScrapeProductsIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp_dir.name) / "test.db"
        init_database(self.db_path)

    def tearDown(self) -> None:
        self.tmp_dir.cleanup()

    def test_scrape_inserts_one_row_per_competitor(self) -> None:
        """With 5 competitors each returning HTML, products_v2 should have 5 rows."""
        def fake_get(url: str, **kwargs: object) -> MockResponse:
            return MockResponse(_HOMEPAGE_HTML)

        with patch("requests.Session.get", side_effect=fake_get):
            result = scrape_products(self.db_path)

        self.assertTrue(result)
        with sqlite3.connect(self.db_path) as conn:
            count = conn.execute("SELECT COUNT(*) FROM products_v2").fetchone()[0]
        self.assertEqual(count, 5)

    def test_scrape_sets_one_way_offered_true(self) -> None:
        """All 5 competitors should have one_way_offered=True when HTML has keywords."""
        def fake_get(url: str, **kwargs: object) -> MockResponse:
            return MockResponse(_HOMEPAGE_HTML)

        with patch("requests.Session.get", side_effect=fake_get):
            scrape_products(self.db_path)

        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute("SELECT one_way_offered FROM products_v2").fetchall()
        self.assertEqual(len(rows), 5)
        for row in rows:
            self.assertEqual(row[0], 1, "one_way_offered should be 1 (True)")

    def test_scrape_idempotent_second_run(self) -> None:
        """Running scrape_products twice on the same date still yields 1 row per competitor."""
        def fake_get(url: str, **kwargs: object) -> MockResponse:
            return MockResponse(_HOMEPAGE_HTML)

        with patch("requests.Session.get", side_effect=fake_get):
            scrape_products(self.db_path)
            scrape_products(self.db_path)

        with sqlite3.connect(self.db_path) as conn:
            count = conn.execute("SELECT COUNT(*) FROM products_v2").fetchone()[0]
        self.assertEqual(count, 5)

    def test_timeout_competitor_skipped_gracefully(self) -> None:
        """If one competitor times out on all paths, scraper continues and returns True."""
        call_count = {"n": 0}

        def fake_get(url: str, **kwargs: object) -> MockResponse:
            call_count["n"] += 1
            # First competitor (id=1) always times out
            if "onwardticket.com" in url:
                raise requests.Timeout("timed out")
            return MockResponse(_HOMEPAGE_HTML)

        with patch("requests.Session.get", side_effect=fake_get):
            result = scrape_products(self.db_path)

        self.assertTrue(result)
        with sqlite3.connect(self.db_path) as conn:
            count = conn.execute("SELECT COUNT(*) FROM products_v2").fetchone()[0]
        # 4 successful competitors
        self.assertGreaterEqual(count, 4)

    def test_http_error_competitor_skipped_gracefully(self) -> None:
        """404 responses are skipped; other competitors continue."""
        def fake_get(url: str, **kwargs: object) -> MockResponse:
            if "bestonwardticket.com" in url:
                return MockResponse("", status_code=404)
            return MockResponse(_HOMEPAGE_HTML)

        with patch("requests.Session.get", side_effect=fake_get):
            result = scrape_products(self.db_path)

        self.assertTrue(result)

    def test_all_competitors_all_false_when_no_keywords(self) -> None:
        """If HTML has no product keywords, all flags should be False."""
        def fake_get(url: str, **kwargs: object) -> MockResponse:
            return MockResponse(_NO_PRODUCTS_HTML)

        with patch("requests.Session.get", side_effect=fake_get):
            scrape_products(self.db_path)

        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT one_way_offered, round_trip_offered, hotel_offered, visa_letter_offered FROM products_v2"
            ).fetchall()

        for row in rows:
            self.assertEqual(row[0], 0)
            self.assertEqual(row[1], 0)
            self.assertEqual(row[2], 0)
            self.assertEqual(row[3], 0)

    def test_returns_false_when_all_competitors_fail(self) -> None:
        """If every competitor page fails, scrape_products returns False."""
        def fake_get(url: str, **kwargs: object) -> MockResponse:
            raise requests.Timeout("timed out")

        with patch("requests.Session.get", side_effect=fake_get):
            result = scrape_products(self.db_path)

        self.assertFalse(result)

    def test_no_time_sleep_called_with_first_path_only(self) -> None:
        """Ensure time.sleep is called between pages (not on first page)."""
        sleep_calls: list[float] = []

        def fake_get(url: str, **kwargs: object) -> MockResponse:
            # Only return HTML for the homepage (path=""), 404 for all others
            if url.endswith("/") or url.count("/") == 2:
                return MockResponse(_HOMEPAGE_HTML)
            return MockResponse("", status_code=404)

        import scrapers.products as prod_module
        original_sleep = prod_module.time.sleep

        def fake_sleep(secs: float) -> None:
            sleep_calls.append(secs)

        prod_module.time.sleep = fake_sleep
        try:
            with patch("requests.Session.get", side_effect=fake_get):
                scrape_products(self.db_path)
        finally:
            prod_module.time.sleep = original_sleep

        # sleep should have been called (between paths for each competitor)
        self.assertGreater(len(sleep_calls), 0)


if __name__ == "__main__":
    unittest.main()
