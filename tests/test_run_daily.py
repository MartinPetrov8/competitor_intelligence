from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest
from _pytest.capture import CaptureFixture
from _pytest.monkeypatch import MonkeyPatch

from init_db import init_database
from run_daily import ScraperTask, configure_logging, print_summary, run_all_scrapers


def _insert_price_row(db_path: Path) -> None:
    with sqlite3.connect(db_path) as conn:
        competitor_id = int(conn.execute("SELECT id FROM competitors ORDER BY id LIMIT 1").fetchone()[0])
        now = datetime.now(UTC).isoformat()
        scrape_date = datetime.now(UTC).date().isoformat()
        conn.execute(
            """
            INSERT INTO prices (
                competitor_id, scrape_date, scraped_at, product_name,
                currency, price_amount, bundle_info, source_url, raw_text
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (competitor_id, scrape_date, now, "Sample product", "USD", 10.0, "bundle", "https://example.com", "$10"),
        )
        conn.commit()


def test_run_all_scrapers_continues_after_failure(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    db_path = tmp_path / "test.db"
    init_database(db_path)

    def fail_scraper(_: Path) -> bool:
        raise RuntimeError("boom")

    def no_data_scraper(_: Path) -> bool:
        return False

    def success_scraper(path: Path) -> bool:
        _insert_price_row(path)
        return True

    monkeypatch.setattr(
        "run_daily.SCRAPER_TASKS",
        (
            ScraperTask("failing", fail_scraper, ("prices",)),
            ScraperTask("no_data", no_data_scraper, ("products",)),
            ScraperTask("success", success_scraper, ("prices",)),
        ),
    )

    results = run_all_scrapers(db_path)

    assert [r.name for r in results] == ["failing", "no_data", "success"]
    assert results[0].status == "failed"
    assert results[1].status == "no_data"
    assert results[2].status == "success"
    assert results[2].rows_inserted == 1


def test_configure_logging_creates_daily_log(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr("run_daily.LOGS_DIR", tmp_path)
    log_path = configure_logging()

    assert log_path.exists()
    assert log_path.parent == tmp_path
    assert log_path.name.startswith("daily_")
    assert log_path.suffix == ".log"


def test_print_summary_outputs_expected_lines(capsys: CaptureFixture[str]) -> None:
    from run_daily import ScraperResult

    results = [
        ScraperResult(name="pricing", status="success", rows_inserted=5, duration_seconds=1.234),
        ScraperResult(name="products", status="failed", rows_inserted=0, duration_seconds=0.5),
    ]

    print_summary(results)
    out = capsys.readouterr().out

    assert "SCRAPER DAILY SUMMARY" in out
    assert "name,status,rows_inserted,duration_seconds" in out
    assert "pricing,success,5,1.234" in out
    assert "products,failed,0,0.500" in out
