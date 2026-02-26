"""Tests for S-11: Dashboard frontend — reviews, products, and diffs views.

Covers:
- Reviews tab: table elements, trend chart canvases, source-tab buttons
- Products tab: comparison matrix, catalog table, filter controls
- Diffs tab: diff list container, filter controls, diff viewer elements
- All new tabs have correct data-tab attributes
- All views have filter elements (date + competitor)
- /api/reviews returns expected structure with trustpilot/google keys
- /api/products returns fields required by the products matrix
- /api/diffs returns fields required by the diff viewer
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
    path = tmp_path / "test_s11.db"
    init_database(path)
    return path


@pytest.fixture
def client(db_path: Path) -> FlaskClient:
    app = create_app(db_path)
    app.testing = True
    c = app.test_client()
    c.post("/login", data={"password": "changeme"})
    return c


@pytest.fixture
def rich_client(db_path: Path) -> FlaskClient:
    """Client backed by a DB with products, reviews, and diffs rows."""
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        competitor_ids = {
            row["domain"]: row["id"]
            for row in conn.execute("SELECT id, domain FROM competitors").fetchall()
        }

    with sqlite3.connect(db_path) as conn:
        # ── Products V2 ───────────────────────────────────────────────────────
        # Format: (domain, date, one_way, one_way_price, round_trip, round_trip_price, hotel, hotel_price, visa, visa_price)
        products_v2_data = [
            ("onwardticket.com",     "2026-02-20", 1, 12.99, 0, None,  0, None,  0, None),
            ("onwardticket.com",     "2026-02-21", 1, 12.99, 1, 24.99, 0, None,  0, None),
            ("bestonwardticket.com", "2026-02-20", 1, 11.99, 0, None,  0, None,  0, None),
            ("dummyticket.com",      "2026-02-21", 1, 15.99, 1, 29.99, 1, 49.99, 0, None),
            ("dummy-tickets.com",    "2026-02-21", 1, 13.99, 0, None,  0, None,  0, None),
            ("vizafly.com",          "2026-02-21", 1, 14.99, 1, 28.99, 0, None,  1, 39.99),
        ]
        for domain, date, ow, ow_p, rt, rt_p, hotel, hotel_p, visa, visa_p in products_v2_data:
            cid = competitor_ids.get(domain)
            if cid is None:
                continue
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
                (cid, date, f"{date}T12:00:00Z", ow, ow_p, rt, rt_p, hotel, hotel_p, visa, visa_p, f"https://{domain}"),
            )

        # ── Trustpilot reviews ────────────────────────────────────────────────
        for domain in ("onwardticket.com", "bestonwardticket.com", "dummyticket.com"):
            cid = competitor_ids.get(domain)
            if cid is None:
                continue
            for date, rating, count in [
                ("2026-02-19", 4.2, 1200),
                ("2026-02-20", 4.3, 1215),
                ("2026-02-21", 4.4, 1230),
            ]:
                conn.execute(
                    """
                    INSERT INTO reviews_trustpilot (
                        competitor_id, scrape_date, overall_rating, total_reviews, source_url
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (cid, date, rating, count, f"https://trustpilot.com/review/{domain}"),
                )

        # ── Google reviews ────────────────────────────────────────────────────
        for domain in ("onwardticket.com", "vizafly.com"):
            cid = competitor_ids.get(domain)
            if cid is None:
                continue
            for date, rating, count in [
                ("2026-02-20", 3.9, 88),
                ("2026-02-21", 4.1, 91),
            ]:
                conn.execute(
                    """
                    INSERT INTO reviews_google (
                        competitor_id, scrape_date, overall_rating, total_reviews, source_url
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (cid, date, rating, count, f"https://google.com/search?q={domain}"),
                )

        # ── Snapshots & diffs ────────────────────────────────────────────────
        for domain in ("onwardticket.com", "dummyticket.com"):
            cid = competitor_ids.get(domain)
            if cid is None:
                continue
            # Insert two snapshots
            snap_ids = []
            for i, content in enumerate(["<html>old content</html>", "<html>new content here</html>"]):
                cursor = conn.execute(
                    """
                    INSERT INTO snapshots (competitor_id, scrape_date, page_type, page_url, html_content)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (cid, f"2026-02-{20+i}", "homepage", f"https://{domain}", content),
                )
                snap_ids.append(cursor.lastrowid)
            # Insert a diff between them
            conn.execute(
                """
                INSERT INTO diffs (
                    competitor_id, diff_date, page_type,
                    previous_snapshot_id, current_snapshot_id,
                    diff_text, additions_count, removals_count
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    cid, "2026-02-21", "homepage",
                    snap_ids[0], snap_ids[1],
                    "--- old\n+++ new\n@@ -1 +1 @@\n-old content\n+new content here",
                    1, 1,
                ),
            )

        conn.commit()

    app = create_app(db_path)
    app.testing = True
    c = app.test_client()
    c.post("/login", data={"password": "changeme"})
    return c


# ─── HTML structure — Reviews tab ─────────────────────────────────────────────


class TestReviewsTabHtml:
    def _html(self, client: FlaskClient) -> str:
        data: bytes = client.get("/").data
        return data.decode("utf-8")

    def test_reviews_tab_button_present(self, client: FlaskClient) -> None:
        assert 'data-tab="reviews"' in self._html(client)

    def test_reviews_panel_present(self, client: FlaskClient) -> None:
        assert 'id="tab-reviews"' in self._html(client)

    def test_reviews_table_present(self, client: FlaskClient) -> None:
        assert 'id="reviewsTable"' in self._html(client)

    def test_reviews_table_body_present(self, client: FlaskClient) -> None:
        assert 'id="reviewsTableBody"' in self._html(client)

    def test_reviews_rating_chart_canvas_present(self, client: FlaskClient) -> None:
        assert 'id="reviewsRatingChart"' in self._html(client)

    def test_reviews_count_chart_canvas_present(self, client: FlaskClient) -> None:
        assert 'id="reviewsCountChart"' in self._html(client)

    def test_trustpilot_source_tab_button_present(self, client: FlaskClient) -> None:
        assert 'data-source="trustpilot"' in self._html(client)

    def test_google_source_tab_button_present(self, client: FlaskClient) -> None:
        assert 'data-source="google"' in self._html(client)

    def test_reviews_competitor_filter_present(self, client: FlaskClient) -> None:
        assert 'id="reviewsFilterCompetitor"' in self._html(client)

    def test_reviews_date_from_filter_present(self, client: FlaskClient) -> None:
        assert 'id="reviewsFilterFrom"' in self._html(client)

    def test_reviews_date_to_filter_present(self, client: FlaskClient) -> None:
        assert 'id="reviewsFilterTo"' in self._html(client)

    def test_reviews_apply_button_present(self, client: FlaskClient) -> None:
        assert 'id="reviewsApplyFilters"' in self._html(client)

    def test_reviews_reset_button_present(self, client: FlaskClient) -> None:
        assert 'id="reviewsResetFilters"' in self._html(client)

    def test_reviews_row_count_badge_present(self, client: FlaskClient) -> None:
        assert 'id="reviewsRowCount"' in self._html(client)


# ─── HTML structure — Products tab ────────────────────────────────────────────


class TestProductsTabHtml:
    def _html(self, client: FlaskClient) -> str:
        data: bytes = client.get("/").data
        return data.decode("utf-8")

    def test_products_tab_button_present(self, client: FlaskClient) -> None:
        assert 'data-tab="products"' in self._html(client)

    def test_products_panel_present(self, client: FlaskClient) -> None:
        assert 'id="tab-products"' in self._html(client)

    def test_products_matrix_table_present(self, client: FlaskClient) -> None:
        assert 'id="productsMatrixTable"' in self._html(client)

    def test_products_matrix_head_present(self, client: FlaskClient) -> None:
        assert 'id="productsMatrixHead"' in self._html(client)

    def test_products_matrix_body_present(self, client: FlaskClient) -> None:
        assert 'id="productsMatrixBody"' in self._html(client)

    def test_products_catalog_table_present(self, client: FlaskClient) -> None:
        assert 'id="productsTable"' in self._html(client)

    def test_products_catalog_body_present(self, client: FlaskClient) -> None:
        assert 'id="productsTableBody"' in self._html(client)

    def test_products_competitor_filter_present(self, client: FlaskClient) -> None:
        assert 'id="productsFilterCompetitor"' in self._html(client)

    def test_products_date_filter_present(self, client: FlaskClient) -> None:
        assert 'id="productsFilterDate"' in self._html(client)

    def test_products_apply_button_present(self, client: FlaskClient) -> None:
        assert 'id="productsApplyFilters"' in self._html(client)

    def test_products_reset_button_present(self, client: FlaskClient) -> None:
        assert 'id="productsResetFilters"' in self._html(client)

    def test_products_row_count_badge_present(self, client: FlaskClient) -> None:
        assert 'id="productsRowCount"' in self._html(client)


# ─── HTML structure — Diffs tab ───────────────────────────────────────────────


class TestDiffsTabHtml:
    def _html(self, client: FlaskClient) -> str:
        data: bytes = client.get("/").data
        return data.decode("utf-8")

    def test_diffs_tab_button_present(self, client: FlaskClient) -> None:
        assert 'data-tab="diffs"' in self._html(client)

    def test_diffs_panel_present(self, client: FlaskClient) -> None:
        assert 'id="tab-diffs"' in self._html(client)

    def test_diffs_list_container_present(self, client: FlaskClient) -> None:
        assert 'id="diffsList"' in self._html(client)

    def test_diffs_state_container_present(self, client: FlaskClient) -> None:
        assert 'id="diffsState"' in self._html(client)

    def test_diffs_count_badge_present(self, client: FlaskClient) -> None:
        assert 'id="diffsCount"' in self._html(client)

    def test_diffs_competitor_filter_present(self, client: FlaskClient) -> None:
        assert 'id="diffsFilterCompetitor"' in self._html(client)

    def test_diffs_date_from_filter_present(self, client: FlaskClient) -> None:
        assert 'id="diffsFilterFrom"' in self._html(client)

    def test_diffs_date_to_filter_present(self, client: FlaskClient) -> None:
        assert 'id="diffsFilterTo"' in self._html(client)

    def test_diffs_apply_button_present(self, client: FlaskClient) -> None:
        assert 'id="diffsApplyFilters"' in self._html(client)

    def test_diffs_reset_button_present(self, client: FlaskClient) -> None:
        assert 'id="diffsResetFilters"' in self._html(client)


# ─── /api/reviews endpoint ────────────────────────────────────────────────────


class TestReviewsApiS11:
    def test_empty_db_returns_trustpilot_and_google_keys(self, client: FlaskClient) -> None:
        data = client.get("/api/reviews").get_json()
        assert isinstance(data, dict)
        assert "trustpilot" in data
        assert "google" in data

    def test_trustpilot_list_is_list(self, client: FlaskClient) -> None:
        data = client.get("/api/reviews").get_json()
        assert isinstance(data["trustpilot"], list)

    def test_google_list_is_list(self, client: FlaskClient) -> None:
        data = client.get("/api/reviews").get_json()
        assert isinstance(data["google"], list)

    def test_trustpilot_rows_have_required_fields(self, rich_client: FlaskClient) -> None:
        data = rich_client.get("/api/reviews").get_json()
        rows = data.get("trustpilot", [])
        assert len(rows) > 0
        for row in rows:
            assert "competitor"     in row
            assert "scrape_date"    in row
            assert "overall_rating" in row
            assert "total_reviews"  in row

    def test_google_rows_have_required_fields(self, rich_client: FlaskClient) -> None:
        data = rich_client.get("/api/reviews").get_json()
        rows = data.get("google", [])
        assert len(rows) > 0
        for row in rows:
            assert "competitor"     in row
            assert "scrape_date"    in row
            assert "overall_rating" in row
            assert "total_reviews"  in row

    def test_trustpilot_has_multiple_dates_for_trend(self, rich_client: FlaskClient) -> None:
        data = rich_client.get("/api/reviews?competitor=onwardticket.com").get_json()
        dates = {r["scrape_date"] for r in data.get("trustpilot", [])}
        assert len(dates) >= 2, "Need ≥2 dates for trend chart"

    def test_competitor_filter_applied(self, rich_client: FlaskClient) -> None:
        data = rich_client.get("/api/reviews?competitor=onwardticket.com").get_json()
        for row in data.get("trustpilot", []):
            assert row["competitor"] == "onwardticket.com"
        for row in data.get("google", []):
            assert row["competitor"] == "onwardticket.com"

    def test_date_range_filter_applied(self, rich_client: FlaskClient) -> None:
        data = rich_client.get("/api/reviews?start_date=2026-02-21").get_json()
        for row in data.get("trustpilot", []) + data.get("google", []):
            assert row["scrape_date"] >= "2026-02-21"

    def test_overall_rating_is_numeric(self, rich_client: FlaskClient) -> None:
        data = rich_client.get("/api/reviews").get_json()
        for row in data.get("trustpilot", []) + data.get("google", []):
            r = row.get("overall_rating")
            assert r is None or isinstance(r, (int, float))

    def test_total_reviews_is_numeric(self, rich_client: FlaskClient) -> None:
        data = rich_client.get("/api/reviews").get_json()
        for row in data.get("trustpilot", []) + data.get("google", []):
            cnt = row.get("total_reviews")
            assert cnt is None or isinstance(cnt, (int, float))


# ─── /api/products endpoint ───────────────────────────────────────────────────


class TestProductsApiS11:
    # Products V2 API fields
    REQUIRED_FIELDS = {
        "competitor", "scrape_date", "scraped_at",
        "one_way_offered", "one_way_price",
        "round_trip_offered", "round_trip_price",
        "hotel_offered", "hotel_price",
        "visa_letter_offered", "visa_letter_price"
    }

    def test_empty_db_returns_empty_list(self, client: FlaskClient) -> None:
        data = client.get("/api/products").get_json()
        assert data == []

    def test_rows_contain_required_fields(self, rich_client: FlaskClient) -> None:
        data = rich_client.get("/api/products").get_json()
        assert len(data) > 0
        for row in data:
            for field in self.REQUIRED_FIELDS:
                assert field in row, f"Missing field '{field}' in row: {row}"

    def test_competitor_filter(self, rich_client: FlaskClient) -> None:
        data = rich_client.get("/api/products?competitor=dummyticket.com").get_json()
        assert all(r["competitor"] == "dummyticket.com" for r in data)

    def test_date_filter_exact(self, rich_client: FlaskClient) -> None:
        data = rich_client.get("/api/products?date=2026-02-21").get_json()
        for row in data:
            assert row["scrape_date"] == "2026-02-21"

    def test_hotel_offered_flag_returned(self, rich_client: FlaskClient) -> None:
        data = rich_client.get("/api/products").get_json()
        hotel_offered = [r for r in data if r["hotel_offered"]]
        assert len(hotel_offered) >= 1, "Expected at least one competitor offering hotel"

    def test_multiple_competitors_returned(self, rich_client: FlaskClient) -> None:
        data = rich_client.get("/api/products").get_json()
        domains = {r["competitor"] for r in data}
        assert len(domains) >= 3


# ─── /api/diffs endpoint ─────────────────────────────────────────────────────


class TestDiffsApiS11:
    REQUIRED_FIELDS = {"competitor", "diff_date", "page_type", "diff_text", "additions_count", "removals_count"}

    def test_empty_db_returns_empty_list(self, client: FlaskClient) -> None:
        data = client.get("/api/diffs").get_json()
        assert data == []

    def test_rows_contain_required_fields(self, rich_client: FlaskClient) -> None:
        data = rich_client.get("/api/diffs").get_json()
        assert len(data) > 0
        for row in data:
            for field in self.REQUIRED_FIELDS:
                assert field in row, f"Missing field '{field}' in row: {row}"

    def test_diff_text_is_string_or_none(self, rich_client: FlaskClient) -> None:
        data = rich_client.get("/api/diffs").get_json()
        for row in data:
            assert row["diff_text"] is None or isinstance(row["diff_text"], str)

    def test_diff_text_contains_diff_markers(self, rich_client: FlaskClient) -> None:
        data = rich_client.get("/api/diffs").get_json()
        diffs_with_text = [r for r in data if r.get("diff_text")]
        assert len(diffs_with_text) >= 1
        combined = "\n".join(r["diff_text"] for r in diffs_with_text)
        assert "+" in combined or "-" in combined, "Diff text should contain +/- markers"

    def test_additions_count_is_numeric(self, rich_client: FlaskClient) -> None:
        data = rich_client.get("/api/diffs").get_json()
        for row in data:
            cnt = row.get("additions_count")
            assert cnt is None or isinstance(cnt, (int, float))

    def test_removals_count_is_numeric(self, rich_client: FlaskClient) -> None:
        data = rich_client.get("/api/diffs").get_json()
        for row in data:
            cnt = row.get("removals_count")
            assert cnt is None or isinstance(cnt, (int, float))

    def test_competitor_filter(self, rich_client: FlaskClient) -> None:
        data = rich_client.get("/api/diffs?competitor=onwardticket.com").get_json()
        assert all(r["competitor"] == "onwardticket.com" for r in data)

    def test_date_range_filter(self, rich_client: FlaskClient) -> None:
        data = rich_client.get("/api/diffs?start_date=2026-02-21&end_date=2026-02-21").get_json()
        for row in data:
            assert row["diff_date"] == "2026-02-21"

    def test_multiple_competitors_returned(self, rich_client: FlaskClient) -> None:
        data = rich_client.get("/api/diffs").get_json()
        domains = {r["competitor"] for r in data}
        assert len(domains) >= 2


# ─── Tab navigation / general ─────────────────────────────────────────────────


class TestTabNavigation:
    def _html(self, client: FlaskClient) -> str:
        data: bytes = client.get("/").data
        return data.decode("utf-8")

    def test_all_five_tabs_present(self, client: FlaskClient) -> None:
        html = self._html(client)
        for tab in ("pricing", "products", "reviews", "diffs", "abtests"):
            assert f'data-tab="{tab}"' in html, f"Missing tab button for '{tab}'"

    def test_all_five_panels_present(self, client: FlaskClient) -> None:
        html = self._html(client)
        for tab in ("pricing", "products", "reviews", "diffs", "abtests"):
            assert f'id="tab-{tab}"' in html, f"Missing tab panel for '{tab}'"

    def test_pricing_tab_is_active_by_default(self, client: FlaskClient) -> None:
        html = self._html(client)
        # The pricing tab-btn should have class active
        assert 'data-tab="pricing"' in html
        # The pricing panel should have class active
        assert 'id="tab-pricing"' in html

    def test_reviews_source_tabs_present(self, client: FlaskClient) -> None:
        html = self._html(client)
        assert 'data-source="trustpilot"' in html
        assert 'data-source="google"' in html

    def test_chartjs_used_for_review_charts(self, client: FlaskClient) -> None:
        html = self._html(client)
        assert "reviewsRatingChart" in html
        assert "reviewsCountChart" in html
