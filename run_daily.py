from __future__ import annotations

import logging
import sqlite3
import time
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Callable

from init_db import init_database
from scrapers.ab_tests import scrape_ab_tests
from scrapers.pricing import scrape_pricing
from scrapers.products import scrape_products
from scrapers.reviews_google import scrape_reviews_google
from scrapers.reviews_trustpilot import scrape_reviews_trustpilot
from scrapers.reviews_sentiment import scrape_reviews_sentiment
from scrapers.snapshots import scrape_snapshots

DEFAULT_DB_PATH = Path("competitor_data.db")
LOGS_DIR = Path("logs")


@dataclass(frozen=True)
class ScraperTask:
    name: str
    func: Callable[[Path], bool]
    tables: tuple[str, ...]


@dataclass(frozen=True)
class ScraperResult:
    name: str
    status: str
    rows_inserted: int
    duration_seconds: float


SCRAPER_TASKS: tuple[ScraperTask, ...] = (
    ScraperTask("pricing", scrape_pricing, ("prices",)),
    ScraperTask("products", scrape_products, ("products",)),
    ScraperTask("snapshots", scrape_snapshots, ("snapshots", "diffs")),
    ScraperTask("reviews_trustpilot", scrape_reviews_trustpilot, ("reviews_trustpilot",)),
    ScraperTask("reviews_google", scrape_reviews_google, ("reviews_google",)),
    ScraperTask("reviews_sentiment", scrape_reviews_sentiment, ("reviews_sentiment",)),
    ScraperTask("ab_tests", scrape_ab_tests, ("ab_tests",)),
)


def _today_utc() -> date:
    return datetime.now(UTC).date()


def _daily_log_path(run_date: date) -> Path:
    return LOGS_DIR / f"daily_{run_date.isoformat()}.log"


def configure_logging(run_date: date | None = None) -> Path:
    date_for_log = run_date or _today_utc()
    log_path = _daily_log_path(date_for_log)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.setLevel(logging.INFO)

    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setFormatter(formatter)
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)

    root_logger.addHandler(file_handler)
    root_logger.addHandler(stream_handler)
    return log_path


def _table_row_count(conn: sqlite3.Connection, table_name: str) -> int:
    row = conn.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()
    if row is None:
        return 0
    return int(row[0])


def _rows_for_tables(db_path: Path, tables: tuple[str, ...]) -> int:
    with sqlite3.connect(db_path) as conn:
        return sum(_table_row_count(conn, table) for table in tables)


def run_all_scrapers(db_path: Path = DEFAULT_DB_PATH) -> list[ScraperResult]:
    init_database(db_path)

    results: list[ScraperResult] = []
    for task in SCRAPER_TASKS:
        started = time.perf_counter()
        before_count = _rows_for_tables(db_path, task.tables)

        status = "success"
        try:
            succeeded = task.func(db_path)
            if not succeeded:
                status = "no_data"
        except Exception:
            logging.exception("%s scraper failed", task.name)
            status = "failed"

        after_count = _rows_for_tables(db_path, task.tables)
        rows_inserted = max(0, after_count - before_count)
        duration = time.perf_counter() - started

        result = ScraperResult(
            name=task.name,
            status=status,
            rows_inserted=rows_inserted,
            duration_seconds=duration,
        )
        results.append(result)
        logging.info(
            "summary scraper=%s status=%s rows_inserted=%s duration_seconds=%.3f",
            result.name,
            result.status,
            result.rows_inserted,
            result.duration_seconds,
        )

    return results


def print_summary(results: list[ScraperResult]) -> None:
    print("SCRAPER DAILY SUMMARY")
    print("name,status,rows_inserted,duration_seconds")
    for result in results:
        print(f"{result.name},{result.status},{result.rows_inserted},{result.duration_seconds:.3f}")


def main() -> int:
    configure_logging()
    results = run_all_scrapers(DEFAULT_DB_PATH)
    print_summary(results)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
