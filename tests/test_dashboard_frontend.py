"""Tests for S-10: Dashboard frontend — pricing view.

Covers:
- / route serves index.html with 200 OK
- HTML contains required structural elements (pricing table, chart canvas,
  date pickers, tab navigation, summary chips)
- /api/competitors endpoint returns expected list
- Pricing API data structure is compatible with the frontend rendering
  (price_amount, competitor, scrape_date fields present)
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from flask.testing import FlaskClient

from dashboard.server import create_app
from init_db import init_database


# ─── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    path = tmp_path / "test_frontend.db"
    init_database(path)
    return path


@pytest.fixture
def client(db_path: Path) -> FlaskClient:
    app = create_app(db_path)
    app.testing = True
    return app.test_client()


@pytest.fixture
def populated_client(db_path: Path) -> FlaskClient:
    """Client backed by a DB pre-populated with price rows for all 5 competitors."""
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        competitor_ids = {
            row["domain"]: row["id"]
            for row in conn.execute("SELECT id, domain FROM competitors").fetchall()
        }

    rows = [
        # (competitor_domain, scrape_date, product_name, tier_name, currency, price_amount, bundle_info)
        ("onwardticket.com",     "2026-02-20", "Onward Ticket",       "Basic",    "USD", 9.99,  "None"),
        ("onwardticket.com",     "2026-02-21", "Onward Ticket",       "Basic",    "USD", 10.99, "None"),
        ("onwardticket.com",     "2026-02-21", "Round Trip",          "Standard", "USD", 18.50, "None"),
        ("bestonwardticket.com", "2026-02-20", "Best Onward Ticket",  "Basic",    "USD", 12.00, "None"),
        ("bestonwardticket.com", "2026-02-21", "Best Onward Ticket",  "Basic",    "USD", 12.50, "None"),
        ("dummyticket.com",      "2026-02-21", "Dummy Ticket",        "Basic",    "USD", 7.99,  "None"),
        ("dummy-tickets.com",    "2026-02-21", "Dummy Tickets",       "Economy",  "USD", 8.49,  "None"),
        ("vizafly.com",          "2026-02-21", "VisaFly Ticket",      "Standard", "USD", 14.99, "None"),
    ]

    with sqlite3.connect(db_path) as conn:
        for domain, date, product, tier, currency, price, bundle in rows:
            cid = competitor_ids.get(domain)
            if cid is None:
                continue
            conn.execute(
                """
                INSERT INTO prices (
                    competitor_id, scrape_date, product_name, tier_name, currency,
                    price_amount, bundle_info, source_url, raw_text
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (cid, date, product, tier, currency, price, bundle,
                 f"https://{domain}", f"${price}"),
            )
        conn.commit()

    app = create_app(db_path)
    app.testing = True
    return app.test_client()


# ─── Route tests ─────────────────────────────────────────────────────────────


class TestIndexRoute:
    def test_root_returns_200(self, client: FlaskClient) -> None:
        resp = client.get("/")
        assert resp.status_code == 200

    def test_root_content_type_is_html(self, client: FlaskClient) -> None:
        resp = client.get("/")
        assert "text/html" in resp.content_type

    def test_root_contains_dashboard_title(self, client: FlaskClient) -> None:
        html = client.get("/").data.decode("utf-8")
        assert "Competitor Intelligence Tracker" in html

    def test_health_still_works_alongside_index(self, client: FlaskClient) -> None:
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.get_json()["status"] == "ok"


# ─── HTML structure ───────────────────────────────────────────────────────────


class TestHtmlStructure:
    """Verify required UI elements are present in the served HTML."""

    def _html(self, client: FlaskClient) -> str:
        return client.get("/").data.decode("utf-8")

    def test_has_pricing_tab_button(self, client: FlaskClient) -> None:
        assert "data-tab=\"pricing\"" in self._html(client)

    def test_has_products_tab_button(self, client: FlaskClient) -> None:
        assert "data-tab=\"products\"" in self._html(client)

    def test_has_reviews_tab_button(self, client: FlaskClient) -> None:
        assert "data-tab=\"reviews\"" in self._html(client)

    def test_has_diffs_tab_button(self, client: FlaskClient) -> None:
        assert "data-tab=\"diffs\"" in self._html(client)

    def test_has_abtests_tab_button(self, client: FlaskClient) -> None:
        assert "data-tab=\"abtests\"" in self._html(client)

    def test_has_pricing_table_element(self, client: FlaskClient) -> None:
        html = self._html(client)
        assert 'id="priceTable"' in html

    def test_has_chart_canvas(self, client: FlaskClient) -> None:
        html = self._html(client)
        assert 'id="priceTrendChart"' in html

    def test_has_date_from_picker(self, client: FlaskClient) -> None:
        html = self._html(client)
        assert 'id="filterDateFrom"' in html
        assert 'type="date"' in html

    def test_has_date_to_picker(self, client: FlaskClient) -> None:
        html = self._html(client)
        assert 'id="filterDateTo"' in html

    def test_has_competitor_filter_select(self, client: FlaskClient) -> None:
        html = self._html(client)
        assert 'id="filterCompetitor"' in html

    def test_has_product_filter_select(self, client: FlaskClient) -> None:
        html = self._html(client)
        assert 'id="filterProduct"' in html

    def test_has_apply_and_reset_buttons(self, client: FlaskClient) -> None:
        html = self._html(client)
        assert 'id="applyFilters"' in html
        assert 'id="resetFilters"' in html

    def test_has_summary_bar(self, client: FlaskClient) -> None:
        html = self._html(client)
        assert 'id="pricingSummary"' in html

    def test_has_comparison_matrix(self, client: FlaskClient) -> None:
        html = self._html(client)
        assert 'id="matrixTable"' in html

    def test_has_loading_state_element(self, client: FlaskClient) -> None:
        html = self._html(client)
        assert 'id="priceTableState"' in html

    def test_has_chartjs_script_tag(self, client: FlaskClient) -> None:
        html = self._html(client)
        assert "chart.js" in html.lower() or "chartjs" in html.lower() or "Chart.js" in html

    def test_has_aria_labels_for_accessibility(self, client: FlaskClient) -> None:
        html = self._html(client)
        assert 'aria-label=' in html

    def test_has_responsive_viewport_meta(self, client: FlaskClient) -> None:
        html = self._html(client)
        assert 'viewport' in html


# ─── Competitors API ──────────────────────────────────────────────────────────


class TestCompetitorsEndpoint:
    def test_returns_200(self, client: FlaskClient) -> None:
        resp = client.get("/api/competitors")
        assert resp.status_code == 200

    def test_returns_list(self, client: FlaskClient) -> None:
        data = client.get("/api/competitors").get_json()
        assert isinstance(data, list)

    def test_returns_all_five_competitors(self, client: FlaskClient) -> None:
        data = client.get("/api/competitors").get_json()
        domains = {c["domain"] for c in data}
        assert "onwardticket.com" in domains
        assert "bestonwardticket.com" in domains
        assert "dummyticket.com" in domains
        assert "dummy-tickets.com" in domains
        assert "vizafly.com" in domains

    def test_each_entry_has_domain_and_id(self, client: FlaskClient) -> None:
        data = client.get("/api/competitors").get_json()
        for entry in data:
            assert "domain" in entry
            assert "id" in entry

    def test_sorted_alphabetically(self, client: FlaskClient) -> None:
        data = client.get("/api/competitors").get_json()
        domains = [c["domain"] for c in data]
        assert domains == sorted(domains)


# ─── Pricing API compatibility ────────────────────────────────────────────────


class TestPricingApiCompatibility:
    """Ensure the pricing API returns fields the frontend JS relies on."""

    REQUIRED_FIELDS = {"competitor", "scrape_date", "product_name", "price_amount", "currency"}

    def test_empty_db_returns_empty_list(self, client: FlaskClient) -> None:
        data = client.get("/api/prices").get_json()
        assert data == []

    def test_price_rows_contain_required_fields(self, populated_client: FlaskClient) -> None:
        data = populated_client.get("/api/prices").get_json()
        assert len(data) > 0
        for row in data:
            for field in self.REQUIRED_FIELDS:
                assert field in row, f"Missing field '{field}' in row: {row}"

    def test_all_five_competitors_present(self, populated_client: FlaskClient) -> None:
        data = populated_client.get("/api/prices").get_json()
        domains = {r["competitor"] for r in data}
        assert "onwardticket.com"     in domains
        assert "bestonwardticket.com" in domains
        assert "dummyticket.com"      in domains
        assert "dummy-tickets.com"    in domains
        assert "vizafly.com"          in domains

    def test_competitor_filter_isolates_one(self, populated_client: FlaskClient) -> None:
        data = populated_client.get("/api/prices?competitor=onwardticket.com").get_json()
        assert all(r["competitor"] == "onwardticket.com" for r in data)
        assert len(data) >= 1

    def test_date_range_filter_start_date(self, populated_client: FlaskClient) -> None:
        data = populated_client.get("/api/prices?start_date=2026-02-21").get_json()
        for row in data:
            assert row["scrape_date"] >= "2026-02-21"

    def test_date_range_filter_end_date(self, populated_client: FlaskClient) -> None:
        data = populated_client.get("/api/prices?end_date=2026-02-20").get_json()
        for row in data:
            assert row["scrape_date"] <= "2026-02-20"

    def test_date_range_filter_combined(self, populated_client: FlaskClient) -> None:
        data = populated_client.get(
            "/api/prices?start_date=2026-02-21&end_date=2026-02-21"
        ).get_json()
        for row in data:
            assert row["scrape_date"] == "2026-02-21"

    def test_price_amount_is_numeric_or_none(self, populated_client: FlaskClient) -> None:
        data = populated_client.get("/api/prices").get_json()
        for row in data:
            pa = row.get("price_amount")
            assert pa is None or isinstance(pa, (int, float)), \
                f"price_amount should be numeric, got {type(pa)}: {pa}"

    def test_multiple_dates_available_for_trend_chart(self, populated_client: FlaskClient) -> None:
        """Trend chart needs at least 2 distinct dates per competitor."""
        data = populated_client.get(
            "/api/prices?competitor=onwardticket.com"
        ).get_json()
        dates = {r["scrape_date"] for r in data}
        assert len(dates) >= 2, "Need ≥2 dates for trend chart"
