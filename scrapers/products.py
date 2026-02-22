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
PRODUCT_PATHS = ("", "/pricing", "/products", "/services", "/onward-ticket")
PRICE_PATTERN = re.compile(r"(?:[$€£]|USD\s*)(\d+(?:[\.,]\d{1,2})?)", re.IGNORECASE)
PRODUCT_KEYWORDS = (
    "ticket",
    "onward",
    "dummy",
    "hotel",
    "reservation",
    "booking",
    "flight",
    "trip",
    "visa",
)


@dataclass(frozen=True)
class ProductRecord:
    competitor_id: int
    scrape_date: str
    scraped_at: str
    product_name: str
    description: str | None
    price_range: str | None
    url: str


def configure_logging() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


def _iter_competitors(conn: sqlite3.Connection) -> Iterable[sqlite3.Row]:
    conn.row_factory = sqlite3.Row
    cursor = conn.execute("SELECT id, domain, base_url FROM competitors ORDER BY id")
    return cursor.fetchall()


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


def _extract_price_range(text: str) -> str | None:
    matches = [m.group(1).replace(",", ".") for m in PRICE_PATTERN.finditer(text)]
    if not matches:
        return None

    values: list[float] = []
    for match in matches:
        try:
            values.append(float(match))
        except ValueError:
            continue

    if not values:
        return None

    minimum = min(values)
    maximum = max(values)
    if minimum == maximum:
        return f"{minimum:.2f}"
    return f"{minimum:.2f}-{maximum:.2f}"


def _is_productish(text: str) -> bool:
    lowered = text.lower()
    return any(keyword in lowered for keyword in PRODUCT_KEYWORDS)


def extract_product_records(*, competitor_id: int, html: str, source_url: str, scrape_date: str, scraped_at: str) -> list[ProductRecord]:
    soup = BeautifulSoup(html, "html.parser")
    records: list[ProductRecord] = []
    seen: set[tuple[str, str | None]] = set()

    containers = soup.find_all(["section", "article", "div", "li"])
    for container in containers:
        heading = container.find(["h1", "h2", "h3", "h4", "strong", "b"])
        if heading is None:
            continue

        product_name = " ".join(heading.get_text(" ", strip=True).split())
        if not product_name or not _is_productish(product_name):
            continue

        text = " ".join(container.get_text(" ", strip=True).split())
        if len(text) < len(product_name):
            continue

        description = text
        if len(description) > 500:
            description = description[:500]

        price_range = _extract_price_range(text)

        dedupe_key = (product_name.lower(), price_range)
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)

        records.append(
            ProductRecord(
                competitor_id=competitor_id,
                scrape_date=scrape_date,
                scraped_at=scraped_at,
                product_name=product_name,
                description=description,
                price_range=price_range,
                url=source_url,
            )
        )

    return records


def _ensure_products_schema(conn: sqlite3.Connection) -> None:
    columns = {row[1] for row in conn.execute("PRAGMA table_info(products)").fetchall()}

    if "price_range" not in columns:
        conn.execute("ALTER TABLE products ADD COLUMN price_range TEXT")
    if "url" not in columns:
        conn.execute("ALTER TABLE products ADD COLUMN url TEXT")


def _get_previous_product_names(conn: sqlite3.Connection, competitor_id: int, scrape_date: str) -> set[str]:
    rows = conn.execute(
        """
        SELECT DISTINCT product_name
        FROM products
        WHERE competitor_id = ? AND scrape_date < ?
        """,
        (competitor_id, scrape_date),
    ).fetchall()
    return {str(row[0]).strip().lower() for row in rows}


def _deduplicate_records(records: list[ProductRecord]) -> list[ProductRecord]:
    unique: list[ProductRecord] = []
    seen: set[tuple[int, str, str | None]] = set()
    for record in records:
        key = (record.competitor_id, record.product_name.strip().lower(), record.price_range)
        if key in seen:
            continue
        seen.add(key)
        unique.append(record)
    return unique


def _store_product_records(conn: sqlite3.Connection, records: list[ProductRecord]) -> int:
    if not records:
        return 0

    _ensure_products_schema(conn)

    new_products_count = 0
    by_competitor: dict[int, list[ProductRecord]] = {}
    for record in records:
        by_competitor.setdefault(record.competitor_id, []).append(record)

    for competitor_id, competitor_records in by_competitor.items():
        prior = _get_previous_product_names(conn, competitor_id, competitor_records[0].scrape_date)
        for record in competitor_records:
            if record.product_name.strip().lower() not in prior:
                new_products_count += 1

    conn.executemany(
        """
        INSERT INTO products (
            competitor_id,
            scrape_date,
            scraped_at,
            product_name,
            description,
            price_range,
            source_url,
            url
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                record.competitor_id,
                record.scrape_date,
                record.scraped_at,
                record.product_name,
                record.description,
                record.price_range,
                record.url,
                record.url,
            )
            for record in records
        ],
    )

    return new_products_count


def scrape_products(db_path: Path = DEFAULT_DB_PATH) -> bool:
    init_database(db_path)

    scrape_date = datetime.now(UTC).date().isoformat()
    scraped_at = datetime.now(UTC).isoformat()
    any_success = False

    with sqlite3.connect(db_path) as conn:
        competitors = list(_iter_competitors(conn))

        with requests.Session() as session:
            for competitor in competitors:
                competitor_records: list[ProductRecord] = []
                base_url = str(competitor["base_url"]).rstrip("/")

                for path in PRODUCT_PATHS:
                    page_url = f"{base_url}{path}"
                    html = _fetch(session, page_url)
                    if html is None:
                        continue

                    extracted = extract_product_records(
                        competitor_id=int(competitor["id"]),
                        html=html,
                        source_url=page_url,
                        scrape_date=scrape_date,
                        scraped_at=scraped_at,
                    )
                    competitor_records.extend(extracted)

                if competitor_records:
                    deduplicated = _deduplicate_records(competitor_records)
                    new_count = _store_product_records(conn, deduplicated)
                    conn.commit()
                    any_success = True
                    logging.info(
                        "Stored %s product rows for %s (%s new)",
                        len(deduplicated),
                        competitor["domain"],
                        new_count,
                    )
                else:
                    logging.warning("No products extracted for %s", competitor["domain"])

    return any_success


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run product catalog scraper")
    parser.add_argument("--db-path", type=Path, default=DEFAULT_DB_PATH, help=f"SQLite DB path (default: {DEFAULT_DB_PATH})")
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
