from __future__ import annotations

import argparse
import logging
import re
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterable, cast

import requests
from bs4 import BeautifulSoup

from init_db import init_database

DEFAULT_DB_PATH = Path("competitor_data.db")
REQUEST_TIMEOUT_SECONDS = 30
PRICING_PATHS = ("", "/pricing", "/prices", "/onward-ticket", "/product")
PRICE_PATTERN = re.compile(r"(?P<currency>[$€£]|USD\s*)(?P<amount>\d+(?:[\.,]\d{1,2})?)", re.IGNORECASE)


@dataclass(frozen=True)
class PriceRecord:
    competitor_id: int
    scrape_date: str
    scraped_at: str
    product_name: str
    price_usd: float
    currency: str
    bundle_info: str | None
    source_url: str
    raw_text: str


def configure_logging() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


def _canonical_currency(raw: str) -> str:
    text = raw.strip().upper()
    if text in {"$", "USD"}:
        return "USD"
    if text == "€":
        return "EUR"
    if text == "£":
        return "GBP"
    return text


def _safe_amount(raw_amount: str) -> float | None:
    normalized = raw_amount.replace(",", ".")
    try:
        return float(normalized)
    except ValueError:
        return None


def extract_price_records(*, competitor_id: int, html: str, source_url: str, scrape_date: str, scraped_at: str) -> list[PriceRecord]:
    soup = BeautifulSoup(html, "html.parser")
    seen: set[tuple[str, float, str]] = set()
    records: list[PriceRecord] = []

    for text_node in soup.find_all(string=PRICE_PATTERN):
        text = " ".join(text_node.split())
        match = PRICE_PATTERN.search(text)
        if match is None:
            continue

        amount = _safe_amount(match.group("amount"))
        if amount is None:
            continue

        element = text_node.parent
        if element is None:
            continue

        heading = element.find_previous(["h1", "h2", "h3", "h4", "strong"]) if hasattr(element, "find_previous") else None
        product_name = " ".join(heading.get_text(" ", strip=True).split()) if heading else "General offering"

        container = element.find_parent(["section", "article", "div", "li"]) if hasattr(element, "find_parent") else None
        bundle_info = None
        if container is not None:
            bundle_text = " ".join(container.get_text(" ", strip=True).split())
            if len(bundle_text) > 500:
                bundle_text = bundle_text[:500]
            bundle_info = bundle_text

        currency = _canonical_currency(match.group("currency"))
        key = (product_name.lower(), amount, currency)
        if key in seen:
            continue
        seen.add(key)

        records.append(
            PriceRecord(
                competitor_id=competitor_id,
                scrape_date=scrape_date,
                scraped_at=scraped_at,
                product_name=product_name,
                price_usd=amount,
                currency=currency,
                bundle_info=bundle_info,
                source_url=source_url,
                raw_text=text,
            )
        )

    return records


def _fetch(session: requests.Session, url: str) -> str | None:
    try:
        response = session.get(url, timeout=REQUEST_TIMEOUT_SECONDS)
        response.raise_for_status()
        return cast(str, response.text)
    except requests.Timeout:
        logging.warning("Timeout after %ss for %s", REQUEST_TIMEOUT_SECONDS, url)
    except requests.RequestException as exc:
        logging.warning("HTTP error while scraping %s: %s", url, exc)
    return None


def _iter_competitors(conn: sqlite3.Connection) -> Iterable[sqlite3.Row]:
    conn.row_factory = sqlite3.Row
    cursor = conn.execute("SELECT id, domain, base_url FROM competitors ORDER BY id")
    return cursor.fetchall()


def _ensure_price_usd_column(conn: sqlite3.Connection) -> None:
    columns = {row[1] for row in conn.execute("PRAGMA table_info(prices)").fetchall()}
    if "price_usd" not in columns:
        conn.execute("ALTER TABLE prices ADD COLUMN price_usd REAL")


def _store_price_records(conn: sqlite3.Connection, records: list[PriceRecord]) -> None:
    if not records:
        return

    _ensure_price_usd_column(conn)
    conn.executemany(
        """
        INSERT INTO prices (
            competitor_id, scrape_date, scraped_at, product_name,
            currency, price_amount, price_usd, bundle_info, source_url, raw_text
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                record.competitor_id,
                record.scrape_date,
                record.scraped_at,
                record.product_name,
                record.currency,
                record.price_usd,
                record.price_usd,
                record.bundle_info,
                record.source_url,
                record.raw_text,
            )
            for record in records
        ],
    )


def scrape_pricing(db_path: Path = DEFAULT_DB_PATH) -> bool:
    init_database(db_path)

    scrape_date = datetime.now(UTC).date().isoformat()
    scraped_at = datetime.now(UTC).isoformat()
    any_success = False

    with sqlite3.connect(db_path) as conn:
        competitors = list(_iter_competitors(conn))

        with requests.Session() as session:
            for competitor in competitors:
                competitor_records: list[PriceRecord] = []
                base_url = str(competitor["base_url"]).rstrip("/")

                for path in PRICING_PATHS:
                    page_url = f"{base_url}{path}"
                    html = _fetch(session, page_url)
                    if html is None:
                        continue

                    extracted = extract_price_records(
                        competitor_id=int(competitor["id"]),
                        html=html,
                        source_url=page_url,
                        scrape_date=scrape_date,
                        scraped_at=scraped_at,
                    )
                    competitor_records.extend(extracted)

                if competitor_records:
                    _store_price_records(conn, competitor_records)
                    conn.commit()
                    any_success = True
                    logging.info("Stored %s price rows for %s", len(competitor_records), competitor["domain"])
                else:
                    logging.warning("No prices extracted for %s", competitor["domain"])

    return any_success


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run pricing scraper")
    parser.add_argument("--db-path", type=Path, default=DEFAULT_DB_PATH, help=f"SQLite DB path (default: {DEFAULT_DB_PATH})")
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
