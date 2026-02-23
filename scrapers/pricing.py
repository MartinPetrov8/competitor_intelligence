from __future__ import annotations

import argparse
import itertools
import json
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
# Paths to attempt per competitor; empty string = base URL (homepage)
PRICING_PATHS = ("", "/pricing", "/prices", "/onward-ticket", "/product")
REQUEST_DELAY_SECONDS = 2.0

# Rotate between 3 realistic UA strings
_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64; rv:120.0) Gecko/20100101 Firefox/120.0",
]
_UA_CYCLE = itertools.cycle(_USER_AGENTS)

# Price: $16, €14, £10 or leading-USD with amount
PRICE_PATTERN = re.compile(
    r"(?:USD\s*)?(?P<currency>[$€£])(?P<amount>\d+(?:[.,]\d{1,2})?)"
)

# Addon label patterns: "Round Trip (+$7)", "7 days (+$7)", "(+$1.00 ...)"
# Capture the addon name from context and the extra amount
ADDON_INLINE_PATTERN = re.compile(
    r"(?P<name>[^(+]+?)\s*\(\+\s*[$€£]?(?P<amount>\d+(?:[.,]\d{1,2})?)"
)

# Pattern to detect addon-only price text — "(+$7)", "(+$10)" — so we don't
# treat the addon delta as the main price
_ADDON_ONLY_PATTERN = re.compile(r"^\s*\(\+\s*[$€£]?\d+(?:[.,]\d{1,2})?")

# JS/HTML noise indicators — skip any raw_text containing these
_NOISE_INDICATORS = (
    "self.__next_f",
    "<![CDATA[",
    "gform.",
    "jQuery(",
    "__next_f",
    "window.__NEXT",
    "function(",
)
_MAX_TEXT_LENGTH = 300


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AddonItem:
    name: str
    price: float


@dataclass(frozen=True)
class PriceV2Record:
    competitor_id: int
    scrape_date: str
    scraped_at: str
    main_price: float | None
    currency: str
    addons: list[AddonItem]
    source_url: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def configure_logging() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


def _is_noise_text(text: str) -> bool:
    """Return True if text looks like JS/HTML noise rather than real pricing copy."""
    if len(text) > _MAX_TEXT_LENGTH:
        return True
    for indicator in _NOISE_INDICATORS:
        if indicator in text:
            return True
    return False


def _safe_float(raw: str) -> float | None:
    try:
        return float(raw.replace(",", "."))
    except ValueError:
        return None


def _canonical_currency(raw: str) -> str:
    sym = raw.strip()
    if sym in {"$", "USD"}:
        return "USD"
    if sym == "€":
        return "EUR"
    if sym == "£":
        return "GBP"
    return sym.upper()


# ---------------------------------------------------------------------------
# __NEXT_DATA__ extraction (Next.js sites)
# ---------------------------------------------------------------------------


def _extract_from_next_data(html: str) -> tuple[float | None, list[AddonItem], str]:
    """
    Parse __NEXT_DATA__ JSON from a Next.js page.

    Returns (main_price, addons, currency).
    """
    soup = BeautifulSoup(html, "html.parser")
    tag = soup.find("script", id="__NEXT_DATA__")
    if not tag or not tag.string:
        return None, [], "USD"

    try:
        data = json.loads(tag.string)
    except json.JSONDecodeError:
        return None, [], "USD"

    text_blob = json.dumps(data)

    # Find all price matches in the JSON blob; deduplicate
    matches: list[tuple[str, float]] = []
    seen_amounts: set[float] = set()
    for m in PRICE_PATTERN.finditer(text_blob):
        amount = _safe_float(m.group("amount"))
        if amount is None:
            continue
        currency = _canonical_currency(m.group("currency"))
        if amount not in seen_amounts:
            seen_amounts.add(amount)
            matches.append((currency, amount))

    if not matches:
        return None, [], "USD"

    # The main price is assumed to be the smallest non-zero price (base offering)
    currency, main_price = min(matches, key=lambda x: x[1])

    # Everything larger is treated as an addon delta
    addons: list[AddonItem] = []
    for cur, amt in matches:
        if amt != main_price:
            addons.append(AddonItem(name=f"Addon ${amt:.2f}", price=amt))

    return main_price, addons, currency


# ---------------------------------------------------------------------------
# Regular HTML extraction
# ---------------------------------------------------------------------------


def _extract_addons_from_text(text: str) -> list[AddonItem]:
    """Extract add-on items from text like 'Round Trip (+$7)', '7 days (+$10)'."""
    addons: list[AddonItem] = []
    for m in ADDON_INLINE_PATTERN.finditer(text):
        name = m.group("name").strip().rstrip("(").strip()
        price = _safe_float(m.group("amount"))
        if name and price is not None and price > 0:
            addons.append(AddonItem(name=name, price=price))
    return addons


def extract_pricing_v2(
    *,
    competitor_id: int,
    html: str,
    source_url: str,
    scrape_date: str,
    scraped_at: str,
) -> PriceV2Record | None:
    """
    Extract a single clean PriceV2Record from an HTML page.

    Returns None if no usable price is found.
    """
    soup = BeautifulSoup(html, "html.parser")
    page_text = soup.get_text(" ", strip=True)

    # Collect all price-containing text nodes, filtered for noise
    price_texts: list[str] = []
    for node in soup.find_all(string=PRICE_PATTERN):
        raw = " ".join(node.split())
        if _is_noise_text(raw):
            continue
        price_texts.append(raw)

    if not price_texts:
        return None

    # Determine main price: use the first (topmost) clean price text that has
    # the smallest dollar amount — typical of "from $X" hero copy.
    best_price: float | None = None
    best_currency = "USD"
    best_text = ""

    for text in price_texts:
        # Skip addon-only price text like "(+$7)" or "Round Trip (+$7)"
        # — these are deltas, not main prices
        if _ADDON_ONLY_PATTERN.search(text) or "(+" in text:
            continue
        m = PRICE_PATTERN.search(text)
        if m is None:
            continue
        amount = _safe_float(m.group("amount"))
        if amount is None:
            continue
        currency = _canonical_currency(m.group("currency"))
        if best_price is None or amount < best_price:
            best_price = amount
            best_currency = currency
            best_text = text

    if best_price is None:
        return None

    # Collect addons: look for "(+$X)" patterns in all price texts
    addons: list[AddonItem] = []
    seen_addon_names: set[str] = set()
    for text in price_texts:
        for addon in _extract_addons_from_text(text):
            key = addon.name.lower()
            if key not in seen_addon_names:
                seen_addon_names.add(key)
                addons.append(addon)

    return PriceV2Record(
        competitor_id=competitor_id,
        scrape_date=scrape_date,
        scraped_at=scraped_at,
        main_price=best_price,
        currency=best_currency,
        addons=addons,
        source_url=source_url,
    )


# ---------------------------------------------------------------------------
# HTTP fetch
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------


def _iter_competitors(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    conn.row_factory = sqlite3.Row
    cursor = conn.execute("SELECT id, domain, base_url FROM competitors ORDER BY id")
    return cursor.fetchall()


def _ensure_prices_v2_schema(conn: sqlite3.Connection) -> None:
    """Ensure prices_v2 table exists (init_database handles this, but be safe)."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS prices_v2 (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            competitor_id INTEGER NOT NULL,
            scrape_date TEXT NOT NULL,
            scraped_at TEXT NOT NULL,
            main_price REAL,
            currency TEXT NOT NULL DEFAULT 'USD',
            addons TEXT,
            source_url TEXT,
            UNIQUE(competitor_id, scrape_date)
        )
        """
    )


def _store_price_v2(conn: sqlite3.Connection, record: PriceV2Record) -> None:
    addons_json: str | None = None
    if record.addons:
        addons_json = json.dumps([{"name": a.name, "price": a.price} for a in record.addons])

    conn.execute(
        """
        INSERT OR REPLACE INTO prices_v2
            (competitor_id, scrape_date, scraped_at, main_price, currency, addons, source_url)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            record.competitor_id,
            record.scrape_date,
            record.scraped_at,
            record.main_price,
            record.currency,
            addons_json,
            record.source_url,
        ),
    )


# ---------------------------------------------------------------------------
# Main scrape function
# ---------------------------------------------------------------------------


def scrape_pricing(db_path: Path = DEFAULT_DB_PATH) -> bool:
    init_database(db_path)

    scrape_date = datetime.now(UTC).date().isoformat()
    scraped_at = datetime.now(UTC).isoformat()
    any_success = False

    with sqlite3.connect(db_path) as conn:
        _ensure_prices_v2_schema(conn)
        competitors = _iter_competitors(conn)

        with requests.Session() as session:
            for competitor in competitors:
                competitor_id = int(competitor["id"])
                domain = str(competitor["domain"])
                base_url = str(competitor["base_url"]).rstrip("/")

                best_record: PriceV2Record | None = None

                for i, path in enumerate(PRICING_PATHS):
                    page_url = f"{base_url}{path}"
                    if i > 0:
                        time.sleep(REQUEST_DELAY_SECONDS)
                    html = _fetch(session, page_url)
                    if html is None:
                        continue

                    # Next.js sites: parse __NEXT_DATA__
                    soup_check = BeautifulSoup(html, "html.parser")
                    if soup_check.find("script", id="__NEXT_DATA__"):
                        main_price, addons, currency = _extract_from_next_data(html)
                        if main_price is not None:
                            best_record = PriceV2Record(
                                competitor_id=competitor_id,
                                scrape_date=scrape_date,
                                scraped_at=scraped_at,
                                main_price=main_price,
                                currency=currency,
                                addons=addons,
                                source_url=page_url,
                            )
                            break

                    # Regular HTML extraction
                    record = extract_pricing_v2(
                        competitor_id=competitor_id,
                        html=html,
                        source_url=page_url,
                        scrape_date=scrape_date,
                        scraped_at=scraped_at,
                    )
                    if record is not None and record.main_price is not None:
                        # Keep this page's result if better than any prior (or first found)
                        if best_record is None or (
                            record.main_price is not None
                            and (best_record.main_price is None or record.main_price < best_record.main_price)
                        ):
                            best_record = record
                        # Homepage result is usually the canonical one — stop after homepage hit
                        if path == "":
                            break

                if best_record is not None:
                    _store_price_v2(conn, best_record)
                    conn.commit()
                    any_success = True
                    addon_count = len(best_record.addons)
                    logging.info(
                        "Stored prices_v2 for %s: main_price=%.2f, addons=%d",
                        domain,
                        best_record.main_price or 0.0,
                        addon_count,
                    )
                else:
                    logging.warning("No prices_v2 extracted for %s", domain)

    return any_success


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run pricing scraper v2")
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
        scrape_pricing(args.db_path)
        return 0
    except sqlite3.Error as exc:
        logging.exception("Database error while scraping prices: %s", exc)
        return 1
    except Exception as exc:  # pragma: no cover
        logging.exception("Unexpected error while scraping prices: %s", exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
