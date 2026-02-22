from __future__ import annotations

import argparse
import hashlib
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
SNAPSHOT_PATHS = {
    "homepage": "",
    "pricing": "/pricing",
}
_TIMESTAMP_PATTERN = re.compile(
    r"(?:\d{4}-\d{2}-\d{2}[T\s]\d{2}:\d{2}(?::\d{2})?(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?)|(?:\b\d{1,2}:\d{2}(?::\d{2})?\s?(?:AM|PM|UTC)?\b)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class SnapshotRecord:
    competitor_id: int
    scrape_date: str
    scraped_at: str
    page_type: str
    page_url: str
    html_content: str
    content_hash: str


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


def _normalize_for_diff(html_content: str) -> list[str]:
    normalized = _TIMESTAMP_PATTERN.sub("[TIMESTAMP]", html_content)
    soup = BeautifulSoup(normalized, "html.parser")
    return [" ".join(text.split()) for text in soup.stripped_strings]


def _build_unified_diff(previous_html: str, current_html: str, from_label: str, to_label: str) -> str:
    import difflib

    previous_lines = _normalize_for_diff(previous_html)
    current_lines = _normalize_for_diff(current_html)

    diff = difflib.unified_diff(
        previous_lines,
        current_lines,
        fromfile=from_label,
        tofile=to_label,
        lineterm="",
    )
    return "\n".join(diff)


def _count_diff_changes(diff_text: str) -> tuple[int, int]:
    additions = 0
    removals = 0
    for line in diff_text.splitlines():
        if line.startswith("+++") or line.startswith("---"):
            continue
        if line.startswith("+"):
            additions += 1
        elif line.startswith("-"):
            removals += 1
    return additions, removals


def _store_snapshot(conn: sqlite3.Connection, snapshot: SnapshotRecord) -> int:
    cursor = conn.execute(
        """
        INSERT INTO snapshots (
            competitor_id,
            scrape_date,
            scraped_at,
            page_type,
            page_url,
            html_content,
            content_hash
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            snapshot.competitor_id,
            snapshot.scrape_date,
            snapshot.scraped_at,
            snapshot.page_type,
            snapshot.page_url,
            snapshot.html_content,
            snapshot.content_hash,
        ),
    )
    if cursor.lastrowid is None:
        raise sqlite3.DatabaseError("Failed to persist snapshot row")
    return int(cursor.lastrowid)


def _latest_previous_snapshot(
    conn: sqlite3.Connection,
    competitor_id: int,
    page_type: str,
    current_snapshot_id: int,
) -> sqlite3.Row | None:
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        """
        SELECT id, html_content
        FROM snapshots
        WHERE competitor_id = ?
          AND page_type = ?
          AND id < ?
        ORDER BY id DESC
        LIMIT 1
        """,
        (competitor_id, page_type, current_snapshot_id),
    ).fetchone()
    return cast(sqlite3.Row | None, row)


def _store_diff_if_changed(conn: sqlite3.Connection, snapshot_id: int, snapshot: SnapshotRecord) -> bool:
    previous = _latest_previous_snapshot(conn, snapshot.competitor_id, snapshot.page_type, snapshot_id)
    if previous is None:
        return False

    previous_id = int(previous["id"])
    previous_html = str(previous["html_content"])
    diff_text = _build_unified_diff(
        previous_html,
        snapshot.html_content,
        f"snapshot:{previous_id}",
        f"snapshot:{snapshot_id}",
    )
    if not diff_text:
        return False

    additions, removals = _count_diff_changes(diff_text)
    if additions == 0 and removals == 0:
        return False

    conn.execute(
        """
        INSERT INTO diffs (
            competitor_id,
            diff_date,
            page_type,
            previous_snapshot_id,
            current_snapshot_id,
            diff_text,
            additions_count,
            removals_count
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            snapshot.competitor_id,
            snapshot.scrape_date,
            snapshot.page_type,
            previous_id,
            snapshot_id,
            diff_text,
            additions,
            removals,
        ),
    )
    return True


def _to_snapshot_record(
    *,
    competitor_id: int,
    page_type: str,
    page_url: str,
    html_content: str,
    scrape_date: str,
    scraped_at: str,
) -> SnapshotRecord:
    content_hash = hashlib.sha256(html_content.encode("utf-8")).hexdigest()
    return SnapshotRecord(
        competitor_id=competitor_id,
        scrape_date=scrape_date,
        scraped_at=scraped_at,
        page_type=page_type,
        page_url=page_url,
        html_content=html_content,
        content_hash=content_hash,
    )


def scrape_snapshots(db_path: Path = DEFAULT_DB_PATH) -> bool:
    init_database(db_path)

    scrape_date = datetime.now(UTC).date().isoformat()
    scraped_at = datetime.now(UTC).isoformat()
    any_success = False

    with sqlite3.connect(db_path) as conn:
        competitors = list(_iter_competitors(conn))

        with requests.Session() as session:
            for competitor in competitors:
                competitor_id = int(competitor["id"])
                base_url = str(competitor["base_url"]).rstrip("/")
                snapshot_count = 0
                diff_count = 0

                for page_type, page_path in SNAPSHOT_PATHS.items():
                    page_url = f"{base_url}{page_path}"
                    html = _fetch(session, page_url)
                    if html is None:
                        continue

                    snapshot = _to_snapshot_record(
                        competitor_id=competitor_id,
                        page_type=page_type,
                        page_url=page_url,
                        html_content=html,
                        scrape_date=scrape_date,
                        scraped_at=scraped_at,
                    )
                    snapshot_id = _store_snapshot(conn, snapshot)
                    snapshot_count += 1
                    if _store_diff_if_changed(conn, snapshot_id, snapshot):
                        diff_count += 1

                conn.commit()
                if snapshot_count > 0:
                    any_success = True
                    logging.info(
                        "Stored %s snapshots for %s (%s diffs)",
                        snapshot_count,
                        competitor["domain"],
                        diff_count,
                    )
                else:
                    logging.warning("No snapshots captured for %s", competitor["domain"])

    return any_success


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run website snapshots scraper")
    parser.add_argument("--db-path", type=Path, default=DEFAULT_DB_PATH, help=f"SQLite DB path (default: {DEFAULT_DB_PATH})")
    return parser.parse_args()


def main() -> int:
    configure_logging()
    args = parse_args()

    try:
        scrape_snapshots(args.db_path)
        return 0
    except sqlite3.Error as exc:
        logging.exception("Database error while scraping snapshots: %s", exc)
        return 1
    except Exception as exc:  # pragma: no cover
        logging.exception("Unexpected error while scraping snapshots: %s", exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
