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

AB_FRAMEWORK_SIGNATURES: dict[str, tuple[str, ...]] = {
    "optimizely": ("optimizely", "cdn.optimizely.com"),
    "vwo": ("visualwebsiteoptimizer", "dev.visualwebsiteoptimizer", "vwo"),
    "google_optimize": ("googleoptimize", "optimize.js", "gtm-optimize"),
    "launchdarkly": ("launchdarkly", "ldclient", "app.launchdarkly.com"),
    "adobe_target": ("adobetarget", "at.js", "tt.omtrdc.net"),
    "split": ("cdn.split.io", "splitio", "split.io"),
    "convert": ("convert.com", "convertglobal", "cdn-4.convertexperiments.com"),
}


@dataclass(frozen=True)
class ABTestRecord:
    competitor_id: int
    scrape_date: str
    scraped_at: str
    page_url: str
    tool_name: str
    evidence: str


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


def _find_match_context(html: str, pattern: str) -> str:
    match = re.search(re.escape(pattern), html, flags=re.IGNORECASE)
    if match is None:
        return pattern
    start = max(0, match.start() - 40)
    end = min(len(html), match.end() + 40)
    return " ".join(html[start:end].split())


def detect_frameworks(html: str) -> list[tuple[str, str]]:
    soup = BeautifulSoup(html, "html.parser")
    script_texts = "\n".join(script.get_text(" ", strip=True) for script in soup.find_all("script"))
    script_srcs = "\n".join(str(script.get("src", "")) for script in soup.find_all("script"))
    searchable = f"{html}\n{script_texts}\n{script_srcs}"

    detections: list[tuple[str, str]] = []
    for tool_name, signatures in AB_FRAMEWORK_SIGNATURES.items():
        for signature in signatures:
            if re.search(re.escape(signature), searchable, flags=re.IGNORECASE):
                evidence = _find_match_context(searchable, signature)
                detections.append((tool_name, evidence[:300]))
                break
    return detections


def _store_records(conn: sqlite3.Connection, records: list[ABTestRecord]) -> None:
    if not records:
        return

    conn.executemany(
        """
        INSERT INTO ab_tests (
            competitor_id, scrape_date, scraped_at, page_url, tool_name, detected, evidence
        ) VALUES (?, ?, ?, ?, ?, 1, ?)
        """,
        [
            (
                record.competitor_id,
                record.scrape_date,
                record.scraped_at,
                record.page_url,
                record.tool_name,
                record.evidence,
            )
            for record in records
        ],
    )


def scrape_ab_tests(db_path: Path = DEFAULT_DB_PATH) -> bool:
    init_database(db_path)

    scrape_date = datetime.now(UTC).date().isoformat()
    scraped_at = datetime.now(UTC).isoformat()
    any_success = False

    with sqlite3.connect(db_path) as conn:
        competitors = list(_iter_competitors(conn))

        with requests.Session() as session:
            for competitor in competitors:
                competitor_id = int(competitor["id"])
                page_url = str(competitor["base_url"]).rstrip("/")
                html = _fetch(session, page_url)
                if html is None:
                    continue

                detections = detect_frameworks(html)
                records = [
                    ABTestRecord(
                        competitor_id=competitor_id,
                        scrape_date=scrape_date,
                        scraped_at=scraped_at,
                        page_url=page_url,
                        tool_name=tool_name,
                        evidence=evidence,
                    )
                    for tool_name, evidence in detections
                ]
                _store_records(conn, records)
                conn.commit()
                any_success = True
                logging.info(
                    "AB framework scan complete for %s: %s detections",
                    competitor["domain"],
                    len(records),
                )

    return any_success


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run A/B testing framework detector")
    parser.add_argument("--db-path", type=Path, default=DEFAULT_DB_PATH, help=f"SQLite DB path (default: {DEFAULT_DB_PATH})")
    return parser.parse_args()


def main() -> int:
    configure_logging()
    args = parse_args()

    try:
        scrape_ab_tests(args.db_path)
        return 0
    except sqlite3.Error as exc:
        logging.exception("Database error while scraping A/B tests: %s", exc)
        return 1
    except Exception as exc:  # pragma: no cover
        logging.exception("Unexpected error while scraping A/B tests: %s", exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
