from __future__ import annotations

import logging
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from flask import Flask, jsonify, request

from init_db import DEFAULT_DB_PATH, init_database

DEFAULT_PORT = 3001


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
                p.product_name,
                p.tier_name,
                p.currency,
                p.price_amount,
                p.bundle_info,
                p.source_url,
                p.raw_text
            FROM prices p
            JOIN competitors c ON c.id = p.competitor_id
            {where_clause}
            ORDER BY p.scrape_date DESC, c.domain ASC, p.id DESC
        """
        with self._connect() as conn:
            return [dict(row) for row in conn.execute(query, params).fetchall()]

    def fetch_products(
        self, competitor: str | None, date_value: str | None, start_date: str | None, end_date: str | None
    ) -> list[dict[str, Any]]:
        where_clause, params = self._build_filters(competitor, date_value, start_date, end_date, "p.scrape_date")
        query = f"""
            SELECT
                c.domain AS competitor,
                p.scrape_date,
                p.scraped_at,
                p.product_name,
                p.product_type,
                p.description,
                p.is_bundle,
                p.source_url
            FROM products p
            JOIN competitors c ON c.id = p.competitor_id
            {where_clause}
            ORDER BY p.scrape_date DESC, c.domain ASC, p.id DESC
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

    return app


def main() -> int:
    app = create_app()
    app.run(host="0.0.0.0", port=DEFAULT_PORT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
