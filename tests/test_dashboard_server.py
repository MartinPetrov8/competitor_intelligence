from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from flask.testing import FlaskClient

from dashboard.server import create_app
from init_db import init_database


@pytest.fixture
def client(tmp_path: Path) -> FlaskClient:
    db_path = tmp_path / "dashboard.db"
    init_database(db_path)
    app = create_app(db_path)
    app.testing = True
    c = app.test_client()
    # Authenticate with the default password so API tests work
    c.post("/login", data={"password": "changeme"})
    return c


def _competitor_id(db_path: Path, domain: str) -> int:
    with sqlite3.connect(db_path) as conn:
        row = conn.execute("SELECT id FROM competitors WHERE domain = ?", (domain,)).fetchone()
    assert row is not None
    return int(row[0])


def _insert_sample_rows(db_path: Path) -> None:
    domain = "onwardticket.com"
    cid = _competitor_id(db_path, domain)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO prices_v2 (
                competitor_id, scrape_date, scraped_at, main_price, currency,
                addons, source_url
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (cid, "2026-02-22", "2026-02-22T12:00:00Z", 12.5, "USD", "[]", "https://onwardticket.com"),
        )
        conn.execute(
            """
            INSERT INTO products_v2 (
                competitor_id, scrape_date, scraped_at,
                one_way_offered, one_way_price,
                round_trip_offered, round_trip_price,
                hotel_offered, hotel_price,
                visa_letter_offered, visa_letter_price,
                source_url
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (cid, "2026-02-22", "2026-02-22T12:00:00Z", 1, 12.5, 0, None, 0, None, 0, None, "https://onwardticket.com"),
        )
        conn.execute(
            """
            INSERT INTO diffs (
                competitor_id, diff_date, page_type, diff_text, additions_count, removals_count
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (cid, "2026-02-22", "homepage", "+ New pricing section", 1, 0),
        )
        conn.execute(
            """
            INSERT INTO reviews_trustpilot (
                competitor_id, scrape_date, overall_rating, total_reviews,
                rating_1, rating_2, rating_3, rating_4, rating_5, source_url
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (cid, "2026-02-22", 4.2, 120, 5, 4, 8, 30, 73, "https://trustpilot.com/review/onwardticket.com"),
        )
        conn.execute(
            """
            INSERT INTO reviews_google (
                competitor_id, scrape_date, overall_rating, total_reviews, source_url
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (cid, "2026-02-22", 4.1, 88, "https://google.com/maps/place/onwardticket"),
        )
        conn.execute(
            """
            INSERT INTO ab_tests (
                competitor_id, scrape_date, page_url, tool_name, detected, evidence
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (cid, "2026-02-22", "https://onwardticket.com", "Optimizely", 1, "window.optimizely"),
        )
        conn.commit()


def test_api_endpoints_handle_empty_database(client: FlaskClient) -> None:
    prices = client.get("/api/prices")
    products = client.get("/api/products")
    reviews = client.get("/api/reviews")
    diffs = client.get("/api/diffs")
    ab_tests = client.get("/api/ab-tests")

    assert prices.status_code == 200
    assert prices.get_json() == []
    assert products.status_code == 200
    assert products.get_json() == []
    assert reviews.status_code == 200
    assert reviews.get_json() == {"trustpilot": [], "google": []}
    assert diffs.status_code == 200
    assert diffs.get_json() == []
    assert ab_tests.status_code == 200
    assert ab_tests.get_json() == []


def test_api_endpoints_return_json_with_data(client: FlaskClient, tmp_path: Path) -> None:
    db_path = tmp_path / "dashboard.db"
    _insert_sample_rows(db_path)

    prices = client.get("/api/prices")
    assert prices.status_code == 200
    price_payload = prices.get_json()
    assert isinstance(price_payload, list)
    assert price_payload[0]["competitor"] == "onwardticket.com"

    products = client.get("/api/products")
    assert products.status_code == 200
    products_data = products.get_json()
    assert len(products_data) > 0
    assert products_data[0]["one_way_offered"] == 1
    assert products_data[0]["one_way_price"] == 12.5

    reviews = client.get("/api/reviews")
    assert reviews.status_code == 200
    review_payload = reviews.get_json()
    assert review_payload["trustpilot"][0]["total_reviews"] == 120
    assert review_payload["google"][0]["total_reviews"] == 88

    diffs = client.get("/api/diffs")
    assert diffs.status_code == 200
    assert diffs.get_json()[0]["diff_text"] == "+ New pricing section"

    ab_tests = client.get("/api/ab-tests")
    assert ab_tests.status_code == 200
    assert ab_tests.get_json()[0]["tool_name"] == "Optimizely"


def test_filtering_by_competitor_and_date(client: FlaskClient, tmp_path: Path) -> None:
    db_path = tmp_path / "dashboard.db"
    _insert_sample_rows(db_path)
    other_id = _competitor_id(db_path, "vizafly.com")

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO prices_v2 (
                competitor_id, scrape_date, scraped_at, main_price, currency,
                addons, source_url
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (other_id, "2026-02-23", "2026-02-23T12:00:00Z", 20.0, "USD", "[]", "https://vizafly.com"),
        )
        conn.commit()

    unfiltered = client.get("/api/prices").get_json()
    assert isinstance(unfiltered, list)
    assert len(unfiltered) == 2

    filtered_domain = client.get("/api/prices?competitor=onwardticket.com").get_json()
    assert isinstance(filtered_domain, list)
    assert len(filtered_domain) == 1
    assert filtered_domain[0]["competitor"] == "onwardticket.com"

    filtered_date = client.get("/api/prices?date=2026-02-23").get_json()
    assert isinstance(filtered_date, list)
    assert len(filtered_date) == 1
    assert filtered_date[0]["competitor"] == "vizafly.com"
