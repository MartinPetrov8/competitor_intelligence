from __future__ import annotations

import argparse
import json
import logging
import re
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterable, cast
from urllib.parse import quote_plus

import requests
from bs4 import BeautifulSoup

from init_db import init_database

import sys as _sys, os as _os
_sys.path.insert(0, _os.path.join(_os.path.dirname(__file__), '..', '..', '..'))
try:
    from security.scraper_sanitize import sanitize_text
except ImportError:
    def sanitize_text(text, field_name="field"):
        return str(text) if text is not None else ""

DEFAULT_DB_PATH = Path("competitor_data.db")
REQUEST_TIMEOUT_SECONDS = 30
GOOGLE_SEARCH_TEMPLATE = "https://www.google.com/search?q={query}"

_JSON_INT_PATTERN = re.compile(r"^\d+$")
_RATING_COUNT_TEXT_PATTERNS = [
    re.compile(r"(?P<rating>\d(?:\.\d)?)\s*(?:out of 5|stars?)\s*(?:from|based on)?\s*(?P<count>\d[\d,]*)\s*(?:reviews?|ratings?)", re.IGNORECASE),
    re.compile(r"(?P<count>\d[\d,]*)\s*(?:Google\s+)?(?:reviews?|ratings?)\s*(?:with\s+an\s+average\s+of\s+)?(?P<rating>\d(?:\.\d)?)", re.IGNORECASE),
]


@dataclass(frozen=True)
class GoogleReviewRecord:
    competitor_id: int
    scrape_date: str
    scraped_at: str
    overall_rating: float | None
    review_count: int | None
    source_url: str


def configure_logging() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


def _iter_competitors(conn: sqlite3.Connection) -> Iterable[sqlite3.Row]:
    conn.row_factory = sqlite3.Row
    return conn.execute("SELECT id, domain FROM competitors ORDER BY id").fetchall()


def _to_int(value: object) -> int | None:
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        digits = value.replace(",", "").strip()
        if _JSON_INT_PATTERN.match(digits):
            return int(digits)
    return None


def _to_float(value: object) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return None
    return None


def _fetch(session: requests.Session, url: str) -> str | None:
    try:
        response = session.get(
            url,
            timeout=REQUEST_TIMEOUT_SECONDS,
            headers={
                "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122 Safari/537.36",
                "Accept-Language": "en-US,en;q=0.9",
            },
        )
        response.raise_for_status()
        return cast(str, response.text)
    except requests.Timeout:
        logging.warning("Timeout after %ss for %s", REQUEST_TIMEOUT_SECONDS, url)
    except requests.RequestException as exc:
        logging.warning("HTTP error while scraping %s: %s", url, exc)
    return None


def _extract_ld_json_objects(soup: BeautifulSoup) -> list[dict[str, object]]:
    objects: list[dict[str, object]] = []
    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        raw = script.string or script.get_text(strip=True)
        if not raw:
            continue
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            continue

        if isinstance(parsed, dict):
            objects.append(parsed)
        elif isinstance(parsed, list):
            objects.extend(item for item in parsed if isinstance(item, dict))
    return objects


def _extract_aggregate_values(soup: BeautifulSoup) -> tuple[float | None, int | None]:
    for item in _extract_ld_json_objects(soup):
        aggregate = item.get("aggregateRating")
        if isinstance(aggregate, dict):
            rating = _to_float(aggregate.get("ratingValue"))
            count = _to_int(aggregate.get("reviewCount"))
            if rating is not None or count is not None:
                return rating, count

        if item.get("@type") == "AggregateRating":
            rating = _to_float(item.get("ratingValue"))
            count = _to_int(item.get("reviewCount"))
            if rating is not None or count is not None:
                return rating, count

    rating_tag = soup.find(attrs={"itemprop": "ratingValue"})
    count_tag = soup.find(attrs={"itemprop": "reviewCount"})
    rating = _to_float(rating_tag.get_text(strip=True) if rating_tag else None)
    count = _to_int(count_tag.get_text(strip=True) if count_tag else None)
    if rating is not None or count is not None:
        return rating, count

    text = soup.get_text(" ", strip=True)
    for pattern in _RATING_COUNT_TEXT_PATTERNS:
        match = pattern.search(text)
        if not match:
            continue
        rating = _to_float(match.group("rating"))
        count = _to_int(match.group("count"))
        if rating is not None or count is not None:
            return rating, count

    return None, None


def extract_google_review_record(*, competitor_id: int, html: str, source_url: str, scrape_date: str, scraped_at: str) -> GoogleReviewRecord | None:
    soup = BeautifulSoup(html, "html.parser")
    overall_rating, review_count = _extract_aggregate_values(soup)

    if overall_rating is None and review_count is None:
        return None

    return GoogleReviewRecord(
        competitor_id=competitor_id,
        scrape_date=scrape_date,
        scraped_at=scraped_at,
        overall_rating=overall_rating,
        review_count=review_count,
        source_url=source_url,
    )


def _ensure_reviews_schema(conn: sqlite3.Connection) -> None:
    columns = {row[1] for row in conn.execute("PRAGMA table_info(reviews_google)").fetchall()}
    migrations = {
        "review_count": "ALTER TABLE reviews_google ADD COLUMN review_count INTEGER",
    }
    for column, statement in migrations.items():
        if column not in columns:
            conn.execute(statement)


def _store_review_record(conn: sqlite3.Connection, record: GoogleReviewRecord) -> None:
    _ensure_reviews_schema(conn)
    conn.execute(
        """
        INSERT INTO reviews_google (
            competitor_id,
            scrape_date,
            scraped_at,
            overall_rating,
            total_reviews,
            review_count,
            source_url
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            record.competitor_id,
            record.scrape_date,
            record.scraped_at,
            record.overall_rating,
            record.review_count,
            record.review_count,
            record.source_url,
        ),
    )


def _google_query_url(domain: str) -> str:
    return GOOGLE_SEARCH_TEMPLATE.format(query=quote_plus(domain))


def scrape_reviews_google(db_path: Path = DEFAULT_DB_PATH) -> bool:
    init_database(db_path)

    scrape_date = datetime.now(UTC).date().isoformat()
    scraped_at = datetime.now(UTC).isoformat()
    any_success = False

    with sqlite3.connect(db_path) as conn:
        competitors = list(_iter_competitors(conn))

        with requests.Session() as session:
            for competitor in competitors:
                competitor_id = int(competitor["id"])
                domain = str(competitor["domain"])
                source_url = _google_query_url(domain)

                html = _fetch(session, source_url)
                if html is None:
                    logging.warning("Google listing unavailable for %s", domain)
                    continue

                record = extract_google_review_record(
                    competitor_id=competitor_id,
                    html=html,
                    source_url=source_url,
                    scrape_date=scrape_date,
                    scraped_at=scraped_at,
                )
                if record is None:
                    logging.warning("No Google review metrics parsed for %s", domain)
                    continue

                _store_review_record(conn, record)
                conn.commit()
                any_success = True
                logging.info("Stored Google review metrics for %s", domain)

    return any_success


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Google reviews scraper")
    parser.add_argument("--db-path", type=Path, default=DEFAULT_DB_PATH, help=f"SQLite DB path (default: {DEFAULT_DB_PATH})")
    return parser.parse_args()


def main() -> int:
    configure_logging()
    args = parse_args()

    try:
        scrape_reviews_google(args.db_path)
        return 0
    except sqlite3.Error as exc:
        logging.exception("Database error while scraping Google reviews: %s", exc)
        return 1
    except Exception as exc:  # pragma: no cover
        logging.exception("Unexpected error while scraping Google reviews: %s", exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
