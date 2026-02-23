from __future__ import annotations

import argparse
import itertools
import logging
import re
import sqlite3
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterable, cast

import requests
from bs4 import BeautifulSoup

from init_db import init_database

DEFAULT_DB_PATH = Path("competitor_data.db")
REQUEST_TIMEOUT_SECONDS = 30
# Paths to attempt per competitor
PRODUCT_PATHS = ("", "/pricing", "/products", "/services", "/onward-ticket")
REQUEST_DELAY_SECONDS = 2.0

# Rotate between 3 realistic UA strings
_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64; rv:120.0) Gecko/20100101 Firefox/120.0",
]
_UA_CYCLE = itertools.cycle(_USER_AGENTS)

# Price pattern: $16, €14, £10, USD 16
PRICE_PATTERN = re.compile(
    r"(?:USD\s*)?(?P<currency>[$€£])(?P<amount>\d+(?:[.,]\d{1,2})?)"
)

# ---------------------------------------------------------------------------
# Category keyword sets
# ---------------------------------------------------------------------------
_ONE_WAY_KEYWORDS = frozenset(
    ["one-way", "one way", "onward ticket", "dummy ticket", "flight reservation"]
)
_ROUND_TRIP_KEYWORDS = frozenset(["round trip", "round-trip", "return", "two-way", "two way"])
_HOTEL_KEYWORDS = frozenset(["hotel", "accommodation", "hostel"])
_VISA_LETTER_KEYWORDS = frozenset(["visa", "support letter", "invitation letter"])


# ---------------------------------------------------------------------------
# Dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ProductV2Record:
    competitor_id: int
    scrape_date: str
    scraped_at: str
    one_way_offered: bool
    one_way_price: float | None
    round_trip_offered: bool
    round_trip_price: float | None
    hotel_offered: bool
    hotel_price: float | None
    visa_letter_offered: bool
    visa_letter_price: float | None
    source_url: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def configure_logging() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


def _iter_competitors(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    conn.row_factory = sqlite3.Row
    cursor = conn.execute("SELECT id, domain, base_url FROM competitors ORDER BY id")
    return cursor.fetchall()


def _fetch(session: requests.Session, url: str) -> str | None:
    session.headers.update({"User-Agent": next(_UA_CYCLE)})
    try:
        response = session.get(url, timeout=REQUEST_TIMEOUT_SECONDS)
        response.raise_for_status()
        return cast(str, response.text)
    except requests.Timeout:
        logging.warning("Timeout after %ss for %s", REQUEST_TIMEOUT_SECONDS, url)
    except requests.RequestException as exc:
        logging.warning("HTTP error while scraping %s: %s", url, exc)
    return None


def _safe_float(raw: str) -> float | None:
    try:
        return float(raw.replace(",", "."))
    except ValueError:
        return None


def _page_text(html: str) -> str:
    """Return lowercased visible text from an HTML page."""
    soup = BeautifulSoup(html, "html.parser")
    return soup.get_text(" ", strip=True).lower()


def _detect_category(page_lower: str, keywords: frozenset[str]) -> bool:
    """Return True if any keyword is found in the lowercased page text."""
    return any(kw in page_lower for kw in keywords)


def _extract_price_near_keyword(page_lower: str, full_html_lower: str, keyword: str) -> float | None:
    """
    Find the first price that appears within ~200 chars of a keyword occurrence.
    Searches in the plain-text version for context, then extracts the price.
    """
    idx = page_lower.find(keyword)
    if idx == -1:
        return None
    snippet = page_lower[max(0, idx - 50) : idx + 200]
    m = PRICE_PATTERN.search(snippet)
    if m is None:
        return None
    return _safe_float(m.group("amount"))


# ---------------------------------------------------------------------------
# Core extraction
# ---------------------------------------------------------------------------


def extract_products_v2(
    *,
    competitor_id: int,
    html_pages: list[tuple[str, str]],  # [(url, html), ...]
    scrape_date: str,
    scraped_at: str,
) -> ProductV2Record:
    """
    Analyse a list of (url, html) pairs and produce ONE ProductV2Record.
    Merges evidence across all pages (OR-combine booleans, take first price found).
    """
    one_way = False
    round_trip = False
    hotel = False
    visa_letter = False
    one_way_price: float | None = None
    round_trip_price: float | None = None
    hotel_price: float | None = None
    visa_letter_price: float | None = None
    primary_url = html_pages[0][0] if html_pages else ""

    for url, html in html_pages:
        page_lower = _page_text(html)
        # Full html lowercase for supplementary price extraction
        html_lower = html.lower()

        if not one_way and _detect_category(page_lower, _ONE_WAY_KEYWORDS):
            one_way = True
            if one_way_price is None:
                # Try a few anchor keywords
                for kw in ("one-way", "one way", "onward ticket", "dummy ticket"):
                    p = _extract_price_near_keyword(page_lower, html_lower, kw)
                    if p is not None:
                        one_way_price = p
                        break

        if not round_trip and _detect_category(page_lower, _ROUND_TRIP_KEYWORDS):
            round_trip = True
            if round_trip_price is None:
                for kw in ("round trip", "round-trip", "return"):
                    p = _extract_price_near_keyword(page_lower, html_lower, kw)
                    if p is not None:
                        round_trip_price = p
                        break

        if not hotel and _detect_category(page_lower, _HOTEL_KEYWORDS):
            hotel = True
            if hotel_price is None:
                for kw in ("hotel", "accommodation", "hostel"):
                    p = _extract_price_near_keyword(page_lower, html_lower, kw)
                    if p is not None:
                        hotel_price = p
                        break

        if not visa_letter and _detect_category(page_lower, _VISA_LETTER_KEYWORDS):
            visa_letter = True
            if visa_letter_price is None:
                for kw in ("visa", "support letter", "invitation letter"):
                    p = _extract_price_near_keyword(page_lower, html_lower, kw)
                    if p is not None:
                        visa_letter_price = p
                        break

    return ProductV2Record(
        competitor_id=competitor_id,
        scrape_date=scrape_date,
        scraped_at=scraped_at,
        one_way_offered=one_way,
        one_way_price=one_way_price,
        round_trip_offered=round_trip,
        round_trip_price=round_trip_price,
        hotel_offered=hotel,
        hotel_price=hotel_price,
        visa_letter_offered=visa_letter,
        visa_letter_price=visa_letter_price,
        source_url=primary_url,
    )


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------


def _ensure_products_v2_schema(conn: sqlite3.Connection) -> None:
    """Ensure products_v2 table exists and has all required columns."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS products_v2 (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            competitor_id INTEGER NOT NULL,
            scrape_date TEXT NOT NULL,
            scraped_at TEXT NOT NULL,
            one_way_offered INTEGER NOT NULL DEFAULT 0,
            one_way_price REAL,
            round_trip_offered INTEGER NOT NULL DEFAULT 0,
            round_trip_price REAL,
            hotel_offered INTEGER NOT NULL DEFAULT 0,
            hotel_price REAL,
            visa_letter_offered INTEGER NOT NULL DEFAULT 0,
            visa_letter_price REAL,
            source_url TEXT,
            UNIQUE(competitor_id, scrape_date)
        )
        """
    )
    # PRAGMA migration: add source_url if missing (for DBs created before this column existed)
    existing_cols = {row[1] for row in conn.execute("PRAGMA table_info(products_v2)").fetchall()}
    if "source_url" not in existing_cols:
        conn.execute("ALTER TABLE products_v2 ADD COLUMN source_url TEXT")


def _store_product_v2(conn: sqlite3.Connection, record: ProductV2Record) -> None:
    conn.execute(
        """
        INSERT OR REPLACE INTO products_v2 (
            competitor_id, scrape_date, scraped_at,
            one_way_offered, one_way_price,
            round_trip_offered, round_trip_price,
            hotel_offered, hotel_price,
            visa_letter_offered, visa_letter_price,
            source_url
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            record.competitor_id,
            record.scrape_date,
            record.scraped_at,
            int(record.one_way_offered),
            record.one_way_price,
            int(record.round_trip_offered),
            record.round_trip_price,
            int(record.hotel_offered),
            record.hotel_price,
            int(record.visa_letter_offered),
            record.visa_letter_price,
            record.source_url,
        ),
    )


# ---------------------------------------------------------------------------
# Main scrape function
# ---------------------------------------------------------------------------


def scrape_products(db_path: Path = DEFAULT_DB_PATH) -> bool:
    init_database(db_path)

    scrape_date = datetime.now(UTC).date().isoformat()
    scraped_at = datetime.now(UTC).isoformat()
    any_success = False

    with sqlite3.connect(db_path) as conn:
        _ensure_products_v2_schema(conn)
        competitors = _iter_competitors(conn)

        with requests.Session() as session:
            for competitor in competitors:
                competitor_id = int(competitor["id"])
                domain = str(competitor["domain"])
                base_url = str(competitor["base_url"]).rstrip("/")

                html_pages: list[tuple[str, str]] = []

                for i, path in enumerate(PRODUCT_PATHS):
                    page_url = f"{base_url}{path}"
                    if i > 0:
                        time.sleep(REQUEST_DELAY_SECONDS)
                    html = _fetch(session, page_url)
                    if html is not None:
                        html_pages.append((page_url, html))

                if not html_pages:
                    logging.warning("No pages fetched for %s — skipping", domain)
                    continue

                record = extract_products_v2(
                    competitor_id=competitor_id,
                    html_pages=html_pages,
                    scrape_date=scrape_date,
                    scraped_at=scraped_at,
                )
                _store_product_v2(conn, record)
                conn.commit()
                any_success = True
                logging.info(
                    "Stored products_v2 for %s: one_way=%s, round_trip=%s, hotel=%s, visa=%s",
                    domain,
                    record.one_way_offered,
                    record.round_trip_offered,
                    record.hotel_offered,
                    record.visa_letter_offered,
                )

    return any_success


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run products scraper v2")
    parser.add_argument(
        "--db-path",
        type=Path,
        default=DEFAULT_DB_PATH,
        help=f"SQLite DB path (default: {DEFAULT_DB_PATH})",
    )
    return parser.parse_args()


def main() -> int:
    configure_logging()
    args = parse_args()

    try:
        scrape_products(args.db_path)
        return 0
    except sqlite3.Error as exc:
        logging.exception("Database error while scraping products: %s", exc)
        return 1
    except Exception as exc:  # pragma: no cover
        logging.exception("Unexpected error while scraping products: %s", exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
