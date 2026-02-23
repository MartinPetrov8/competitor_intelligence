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

import requests
from bs4 import BeautifulSoup

from init_db import init_database

DEFAULT_DB_PATH = Path("competitor_data.db")
REQUEST_TIMEOUT_SECONDS = 30
TRUSTPILOT_URL_TEMPLATE = "https://www.trustpilot.com/review/{domain}"

_JSON_INT_PATTERN = re.compile(r"^\d+$")
_STAR_COUNT_FALLBACK_PATTERN = re.compile(
    r"(?P<count>\d[\d,]*)\s+(?:reviews?|ratings?)\s+for\s+(?P<stars>[1-5])\s*[- ]?star",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class TrustpilotReviewRecord:
    competitor_id: int
    scrape_date: str
    scraped_at: str
    overall_rating: float | None
    review_count: int | None
    stars_5: int | None
    stars_4: int | None
    stars_3: int | None
    stars_2: int | None
    stars_1: int | None
    source_url: str


def configure_logging() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


def _iter_competitors(conn: sqlite3.Connection) -> Iterable[sqlite3.Row]:
    conn.row_factory = sqlite3.Row
    return conn.execute("SELECT id, domain FROM competitors ORDER BY id").fetchall()


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
            return _to_float(aggregate.get("ratingValue")), _to_int(aggregate.get("reviewCount"))

        if item.get("@type") == "AggregateRating":
            return _to_float(item.get("ratingValue")), _to_int(item.get("reviewCount"))

    return None, None


def _extract_nextjs_data(soup: BeautifulSoup) -> tuple[float | None, int | None, dict[int, int]]:
    """Extract trustScore, numberOfReviews and star distribution from __NEXT_DATA__ JSON."""
    script = soup.find("script", id="__NEXT_DATA__")
    if script is None:
        return None, None, {}

    raw = script.string or script.get_text(strip=True)
    if not raw:
        return None, None, {}

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None, None, {}

    overall_rating: float | None = None
    review_count: int | None = None
    distribution: dict[int, int] = {}

    def _search(obj: object) -> None:
        nonlocal overall_rating, review_count
        if isinstance(obj, dict):
            if "trustScore" in obj and overall_rating is None:
                overall_rating = _to_float(obj["trustScore"])
            if "numberOfReviews" in obj and review_count is None:
                # numberOfReviews may be an int or a dict with 'total'
                val = obj["numberOfReviews"]
                if isinstance(val, dict):
                    review_count = _to_int(val.get("total"))
                else:
                    review_count = _to_int(val)
            # Look for star distribution: list of dicts with 'stars' and 'count'
            for key in ("reviewsDistribution", "ratingDistribution", "distribution"):
                if key in obj and isinstance(obj[key], list):
                    for entry in obj[key]:
                        if isinstance(entry, dict):
                            star = _to_int(entry.get("stars", entry.get("star")))
                            count = _to_int(entry.get("count"))
                            if star is not None and count is not None and 1 <= star <= 5:
                                distribution[star] = count
            for v in obj.values():
                _search(v)
        elif isinstance(obj, list):
            for item in obj:
                _search(item)

    _search(data)
    return overall_rating, review_count, distribution


def _extract_distribution_from_json_blob(soup: BeautifulSoup) -> dict[int, int]:
    distribution: dict[int, int] = {}

    for script in soup.find_all("script"):
        text = script.string or script.get_text(" ", strip=True)
        if not text or "star" not in text.lower():
            continue

        for match in re.finditer(r'"stars"\s*:\s*"?(?P<stars>[1-5])"?[^\n\r{}\[\]]{0,120}?"count"\s*:\s*(?P<count>\d[\d,]*)', text):
            star = int(match.group("stars"))
            count = int(match.group("count").replace(",", ""))
            distribution[star] = count

    return distribution


def _extract_distribution_from_text(soup: BeautifulSoup) -> dict[int, int]:
    text = soup.get_text(" ", strip=True)
    distribution: dict[int, int] = {}
    for match in _STAR_COUNT_FALLBACK_PATTERN.finditer(text):
        star = int(match.group("stars"))
        count = int(match.group("count").replace(",", ""))
        distribution[star] = count
    return distribution


def extract_trustpilot_review_record(*, competitor_id: int, html: str, source_url: str, scrape_date: str, scraped_at: str) -> TrustpilotReviewRecord | None:
    soup = BeautifulSoup(html, "html.parser")

    # Try Next.js __NEXT_DATA__ block first (Trustpilot's current format)
    overall_rating, review_count, distribution = _extract_nextjs_data(soup)

    # Fall back to LD+JSON schema.org extraction
    if overall_rating is None and review_count is None:
        overall_rating, review_count = _extract_aggregate_values(soup)

    if not distribution:
        distribution = _extract_distribution_from_json_blob(soup)
    if not distribution:
        distribution = _extract_distribution_from_text(soup)

    if overall_rating is None and review_count is None and not distribution:
        return None

    return TrustpilotReviewRecord(
        competitor_id=competitor_id,
        scrape_date=scrape_date,
        scraped_at=scraped_at,
        overall_rating=overall_rating,
        review_count=review_count,
        stars_5=distribution.get(5),
        stars_4=distribution.get(4),
        stars_3=distribution.get(3),
        stars_2=distribution.get(2),
        stars_1=distribution.get(1),
        source_url=source_url,
    )


def _ensure_reviews_schema(conn: sqlite3.Connection) -> None:
    columns = {row[1] for row in conn.execute("PRAGMA table_info(reviews_trustpilot)").fetchall()}
    migrations = {
        "review_count": "ALTER TABLE reviews_trustpilot ADD COLUMN review_count INTEGER",
        "stars_5": "ALTER TABLE reviews_trustpilot ADD COLUMN stars_5 INTEGER",
        "stars_4": "ALTER TABLE reviews_trustpilot ADD COLUMN stars_4 INTEGER",
        "stars_3": "ALTER TABLE reviews_trustpilot ADD COLUMN stars_3 INTEGER",
        "stars_2": "ALTER TABLE reviews_trustpilot ADD COLUMN stars_2 INTEGER",
        "stars_1": "ALTER TABLE reviews_trustpilot ADD COLUMN stars_1 INTEGER",
    }
    for column, statement in migrations.items():
        if column not in columns:
            conn.execute(statement)


def _store_review_record(conn: sqlite3.Connection, record: TrustpilotReviewRecord) -> None:
    _ensure_reviews_schema(conn)
    conn.execute(
        """
        INSERT INTO reviews_trustpilot (
            competitor_id,
            scrape_date,
            scraped_at,
            overall_rating,
            total_reviews,
            review_count,
            rating_5,
            rating_4,
            rating_3,
            rating_2,
            rating_1,
            stars_5,
            stars_4,
            stars_3,
            stars_2,
            stars_1,
            source_url
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            record.competitor_id,
            record.scrape_date,
            record.scraped_at,
            record.overall_rating,
            record.review_count,
            record.review_count,
            record.stars_5,
            record.stars_4,
            record.stars_3,
            record.stars_2,
            record.stars_1,
            record.stars_5,
            record.stars_4,
            record.stars_3,
            record.stars_2,
            record.stars_1,
            record.source_url,
        ),
    )


def scrape_reviews_trustpilot(db_path: Path = DEFAULT_DB_PATH) -> bool:
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
                page_url = TRUSTPILOT_URL_TEMPLATE.format(domain=domain)

                html = _fetch(session, page_url)
                if html is None:
                    logging.warning("Trustpilot page unavailable for %s", domain)
                    continue

                record = extract_trustpilot_review_record(
                    competitor_id=competitor_id,
                    html=html,
                    source_url=page_url,
                    scrape_date=scrape_date,
                    scraped_at=scraped_at,
                )
                if record is None:
                    logging.warning("No Trustpilot review metrics parsed for %s", domain)
                    continue

                _store_review_record(conn, record)
                conn.commit()
                any_success = True
                logging.info("Stored Trustpilot review metrics for %s", domain)

    return any_success


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Trustpilot review scraper")
    parser.add_argument("--db-path", type=Path, default=DEFAULT_DB_PATH, help=f"SQLite DB path (default: {DEFAULT_DB_PATH})")
    return parser.parse_args()


def main() -> int:
    configure_logging()
    args = parse_args()

    try:
        scrape_reviews_trustpilot(args.db_path)
        return 0
    except sqlite3.Error as exc:
        logging.exception("Database error while scraping Trustpilot reviews: %s", exc)
        return 1
    except Exception as exc:  # pragma: no cover
        logging.exception("Unexpected error while scraping Trustpilot reviews: %s", exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
