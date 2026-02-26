from __future__ import annotations

import json
import logging
import os
import secrets
import sqlite3
from datetime import UTC, datetime
from functools import wraps
from pathlib import Path
from typing import Any, Callable

from flask import Flask, jsonify, redirect, render_template, request, send_from_directory, session, url_for

from init_db import DEFAULT_DB_PATH, init_database

DEFAULT_PORT = 3001

_AUTH_SESSION_KEY = "authenticated"

# Public routes that skip authentication
_PUBLIC_ROUTES = {"/login", "/health"}


def _get_password() -> str:
    """Return the dashboard password from the environment, defaulting to 'changeme'."""
    return os.environ.get("DASHBOARD_PASSWORD", "changeme")


class DashboardStore:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self._columns_cache: dict[str, set[str]] = {}

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _table_columns(self, table_name: str) -> set[str]:
        cached = self._columns_cache.get(table_name)
        if cached is not None:
            return cached

        with self._connect() as conn:
            rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
        columns = {str(row[1]) for row in rows}
        self._columns_cache[table_name] = columns
        return columns

    def _metric_expr(self, table_name: str, preferred: str, fallback: str, alias: str) -> str:
        columns = self._table_columns(table_name)
        if preferred in columns and fallback in columns:
            return f"COALESCE(r.{preferred}, r.{fallback}) AS {alias}"
        if preferred in columns:
            return f"r.{preferred} AS {alias}"
        return f"r.{fallback} AS {alias}"

    def _build_filters(
        self,
        competitor: str | None,
        date_value: str | None,
        start_date: str | None,
        end_date: str | None,
        date_column: str,
    ) -> tuple[str, list[Any]]:
        clauses: list[str] = []
        params: list[Any] = []

        if competitor:
            clauses.append("c.domain = ?")
            params.append(competitor)

        if date_value:
            clauses.append(f"{date_column} = ?")
            params.append(date_value)
        else:
            if start_date:
                clauses.append(f"{date_column} >= ?")
                params.append(start_date)
            if end_date:
                clauses.append(f"{date_column} <= ?")
                params.append(end_date)

        if not clauses:
            return "", params
        return f"WHERE {' AND '.join(clauses)}", params

    def fetch_prices(
        self, competitor: str | None, date_value: str | None, start_date: str | None, end_date: str | None
    ) -> list[dict[str, Any]]:
        where_clause, params = self._build_filters(competitor, date_value, start_date, end_date, "p.scrape_date")
        query = f"""
            SELECT
                c.domain AS competitor,
                p.scrape_date,
                p.scraped_at,
                p.main_price,
                p.currency,
                p.addons,
                p.source_url,
                LAG(p.main_price) OVER (PARTITION BY p.competitor_id ORDER BY p.scrape_date) AS prev_price
            FROM prices_v2 p
            JOIN competitors c ON c.id = p.competitor_id
            {where_clause}
            ORDER BY p.scrape_date DESC, c.domain ASC
        """
        with self._connect() as conn:
            rows = [dict(row) for row in conn.execute(query, params).fetchall()]
            for row in rows:
                # Parse addons JSON
                try:
                    row['addons'] = json.loads(row['addons']) if row['addons'] else []
                except Exception:
                    row['addons'] = []
                # Price change indicator
                if row.get('prev_price') is not None and row.get('main_price') is not None:
                    diff = row['main_price'] - row['prev_price']
                    row['price_change'] = round(diff, 2)
                    row['price_change_direction'] = 'up' if diff > 0 else ('down' if diff < 0 else 'same')
                else:
                    row['price_change'] = None
                    row['price_change_direction'] = 'none'
            return rows

    def fetch_products(
        self, competitor: str | None, date_value: str | None, start_date: str | None, end_date: str | None
    ) -> list[dict[str, Any]]:
        where_clause, params = self._build_filters(competitor, date_value, start_date, end_date, "p.scrape_date")
        query = f"""
            SELECT
                c.domain AS competitor,
                p.scrape_date,
                p.scraped_at,
                p.one_way_offered,
                p.one_way_price,
                p.round_trip_offered,
                p.round_trip_price,
                p.hotel_offered,
                p.hotel_price,
                p.visa_letter_offered,
                p.visa_letter_price
            FROM products_v2 p
            JOIN competitors c ON c.id = p.competitor_id
            {where_clause}
            ORDER BY p.scrape_date DESC, c.domain ASC
        """
        with self._connect() as conn:
            return [dict(row) for row in conn.execute(query, params).fetchall()]

    def fetch_diffs(
        self, competitor: str | None, date_value: str | None, start_date: str | None, end_date: str | None
    ) -> list[dict[str, Any]]:
        where_clause, params = self._build_filters(competitor, date_value, start_date, end_date, "d.diff_date")
        query = f"""
            SELECT
                c.domain AS competitor,
                d.diff_date,
                d.created_at,
                d.page_type,
                d.previous_snapshot_id,
                d.current_snapshot_id,
                d.diff_text,
                d.additions_count,
                d.removals_count
            FROM diffs d
            JOIN competitors c ON c.id = d.competitor_id
            {where_clause}
            ORDER BY d.diff_date DESC, c.domain ASC, d.id DESC
        """
        with self._connect() as conn:
            return [dict(row) for row in conn.execute(query, params).fetchall()]

    def fetch_ab_tests(
        self, competitor: str | None, date_value: str | None, start_date: str | None, end_date: str | None
    ) -> list[dict[str, Any]]:
        where_clause, params = self._build_filters(competitor, date_value, start_date, end_date, "a.scrape_date")
        query = f"""
            SELECT
                c.domain AS competitor,
                a.scrape_date,
                a.scraped_at,
                a.page_url,
                a.tool_name,
                a.detected,
                a.evidence
            FROM ab_tests a
            JOIN competitors c ON c.id = a.competitor_id
            {where_clause}
            ORDER BY a.scrape_date DESC, c.domain ASC, a.id DESC
        """
        with self._connect() as conn:
            return [dict(row) for row in conn.execute(query, params).fetchall()]

    def fetch_competitors(self) -> list[dict[str, Any]]:
        query = "SELECT id, domain, base_url FROM competitors ORDER BY domain ASC"
        with self._connect() as conn:
            return [dict(row) for row in conn.execute(query).fetchall()]

    def get_scraper_count(self) -> int:
        """Return the count of scrapers from the competitors table.
        
        Returns:
            Integer count of competitors/scrapers in the database.
            
        Raises:
            sqlite3.Error: If database query fails.
        """
        query = "SELECT COUNT(*) as count FROM competitors"
        try:
            with self._connect() as conn:
                row = conn.execute(query).fetchone()
                return int(row["count"])
        except sqlite3.Error:
            logging.exception("Failed to get scraper count")
            raise

    def get_last_run_timestamp(self) -> str | None:
        """Return the maximum scraped_at timestamp across all scraping tables.
        
        Queries scraped_at columns from prices_v2, products_v2, reviews_trustpilot,
        reviews_google, ab_tests, and snapshots tables and returns the most recent
        timestamp.
        
        Returns:
            ISO 8601 timestamp string of the most recent scrape, or None if no
            timestamps exist in any table.
            
        Raises:
            sqlite3.Error: If database query fails.
        """
        query = """
            SELECT MAX(scraped_at) as last_run FROM (
                SELECT MAX(scraped_at) as scraped_at FROM prices_v2
                UNION ALL
                SELECT MAX(scraped_at) as scraped_at FROM products_v2
                UNION ALL
                SELECT MAX(scraped_at) as scraped_at FROM reviews_trustpilot
                UNION ALL
                SELECT MAX(scraped_at) as scraped_at FROM reviews_google
                UNION ALL
                SELECT MAX(scraped_at) as scraped_at FROM ab_tests
                UNION ALL
                SELECT MAX(scraped_at) as scraped_at FROM snapshots
            )
        """
        try:
            with self._connect() as conn:
                row = conn.execute(query).fetchone()
                result = row["last_run"]
                return str(result) if result is not None else None
        except sqlite3.Error:
            logging.exception("Failed to get last run timestamp")
            raise

    def fetch_reviews(
        self, competitor: str | None, date_value: str | None, start_date: str | None, end_date: str | None
    ) -> dict[str, list[dict[str, Any]]]:
        trustpilot_where, trustpilot_params = self._build_filters(
            competitor, date_value, start_date, end_date, "r.scrape_date"
        )
        google_where, google_params = self._build_filters(competitor, date_value, start_date, end_date, "r.scrape_date")

        trustpilot_total_reviews = self._metric_expr(
            "reviews_trustpilot", "review_count", "total_reviews", "total_reviews"
        )
        trustpilot_stars_1 = self._metric_expr("reviews_trustpilot", "stars_1", "rating_1", "stars_1")
        trustpilot_stars_2 = self._metric_expr("reviews_trustpilot", "stars_2", "rating_2", "stars_2")
        trustpilot_stars_3 = self._metric_expr("reviews_trustpilot", "stars_3", "rating_3", "stars_3")
        trustpilot_stars_4 = self._metric_expr("reviews_trustpilot", "stars_4", "rating_4", "stars_4")
        trustpilot_stars_5 = self._metric_expr("reviews_trustpilot", "stars_5", "rating_5", "stars_5")
        google_total_reviews = self._metric_expr("reviews_google", "review_count", "total_reviews", "total_reviews")

        trustpilot_query = f"""
            SELECT
                c.domain AS competitor,
                r.scrape_date,
                r.scraped_at,
                r.overall_rating,
                {trustpilot_total_reviews},
                {trustpilot_stars_1},
                {trustpilot_stars_2},
                {trustpilot_stars_3},
                {trustpilot_stars_4},
                {trustpilot_stars_5},
                r.source_url
            FROM reviews_trustpilot r
            JOIN competitors c ON c.id = r.competitor_id
            {trustpilot_where}
            ORDER BY r.scrape_date DESC, c.domain ASC, r.id DESC
        """
        google_query = f"""
            SELECT
                c.domain AS competitor,
                r.scrape_date,
                r.scraped_at,
                r.overall_rating,
                {google_total_reviews},
                r.source_url
            FROM reviews_google r
            JOIN competitors c ON c.id = r.competitor_id
            {google_where}
            ORDER BY r.scrape_date DESC, c.domain ASC, r.id DESC
        """

        with self._connect() as conn:
            trustpilot_rows = [dict(row) for row in conn.execute(trustpilot_query, trustpilot_params).fetchall()]
            google_rows = [dict(row) for row in conn.execute(google_query, google_params).fetchall()]

        return {"trustpilot": trustpilot_rows, "google": google_rows}


def _query_param(name: str) -> str | None:
    value = request.args.get(name)
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


def _json_error(message: str, code: int = 500) -> tuple[Any, int]:
    return jsonify({"error": message}), code


def create_app(db_path: Path = DEFAULT_DB_PATH) -> Flask:
    init_database(db_path)
    store = DashboardStore(db_path)

    app = Flask(__name__)
    app.secret_key = os.environ.get("SECRET_KEY") or secrets.token_hex(32)

    _static_dir = Path(__file__).parent / "static"

    @app.before_request
    def require_auth() -> Any:
        if request.path in _PUBLIC_ROUTES or request.path.startswith("/static"):
            return None
        if not session.get(_AUTH_SESSION_KEY):
            return redirect(url_for("login"))
        return None

    @app.route("/login", methods=["GET", "POST"])
    def login() -> Any:
        if request.method == "POST":
            submitted = request.form.get("password", "")
            if secrets.compare_digest(submitted, _get_password()):
                session[_AUTH_SESSION_KEY] = True
                next_url = request.args.get("next") or "/"
                return redirect(next_url)
            return render_template("login.html", error="Incorrect password. Please try again.")
        return render_template("login.html", error=None)

    @app.route("/logout")
    def logout() -> Any:
        session.pop(_AUTH_SESSION_KEY, None)
        return redirect(url_for("login"))

    @app.route("/")
    def index() -> Any:
        return send_from_directory(str(_static_dir), "index.html")

    @app.get("/health")
    def health() -> Any:
        return jsonify(
            {
                "status": "ok",
                "timestamp": datetime.now(UTC).isoformat(),
            }
        )

    @app.get("/api/prices")
    def api_prices() -> Any:
        try:
            data = store.fetch_prices(
                competitor=_query_param("competitor"),
                date_value=_query_param("date"),
                start_date=_query_param("start_date"),
                end_date=_query_param("end_date"),
            )
            return jsonify(data)
        except sqlite3.Error:
            logging.exception("Failed to load pricing data")
            return _json_error("Failed to load pricing data")

    @app.get("/api/products")
    def api_products() -> Any:
        try:
            data = store.fetch_products(
                competitor=_query_param("competitor"),
                date_value=_query_param("date"),
                start_date=_query_param("start_date"),
                end_date=_query_param("end_date"),
            )
            return jsonify(data)
        except sqlite3.Error:
            logging.exception("Failed to load product data")
            return _json_error("Failed to load product data")

    @app.get("/api/reviews")
    def api_reviews() -> Any:
        try:
            data = store.fetch_reviews(
                competitor=_query_param("competitor"),
                date_value=_query_param("date"),
                start_date=_query_param("start_date"),
                end_date=_query_param("end_date"),
            )
            return jsonify(data)
        except sqlite3.Error:
            logging.exception("Failed to load review data")
            return _json_error("Failed to load review data")

    @app.get("/api/diffs")
    def api_diffs() -> Any:
        try:
            data = store.fetch_diffs(
                competitor=_query_param("competitor"),
                date_value=_query_param("date"),
                start_date=_query_param("start_date"),
                end_date=_query_param("end_date"),
            )
            return jsonify(data)
        except sqlite3.Error:
            logging.exception("Failed to load diff data")
            return _json_error("Failed to load diff data")

    @app.get("/api/ab-tests")
    def api_ab_tests() -> Any:
        try:
            data = store.fetch_ab_tests(
                competitor=_query_param("competitor"),
                date_value=_query_param("date"),
                start_date=_query_param("start_date"),
                end_date=_query_param("end_date"),
            )
            return jsonify(data)
        except sqlite3.Error:
            logging.exception("Failed to load A/B testing data")
            return _json_error("Failed to load A/B testing data")

    @app.get("/api/competitors")
    def api_competitors() -> Any:
        try:
            data = store.fetch_competitors()
            return jsonify(data)
        except sqlite3.Error:
            logging.exception("Failed to load competitors")
            return _json_error("Failed to load competitors")

    return app


def main() -> int:
    app = create_app()
    port = int(os.environ.get("DASHBOARD_PORT", DEFAULT_PORT))
    app.run(host="0.0.0.0", port=port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
