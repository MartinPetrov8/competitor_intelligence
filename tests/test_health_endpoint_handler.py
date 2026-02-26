from __future__ import annotations

import json
import sqlite3
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from unittest import TestCase

from flask.testing import FlaskClient

from dashboard.server import create_app
from init_db import init_database


class HealthEndpointHandlerTests(TestCase):
    """Test suite for US-004: Update /health route handler to return enhanced JSON response."""

    def setUp(self) -> None:
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp_dir.name) / "test_health.db"
        init_database(self.db_path)
        self.app = create_app(self.db_path)
        self.client = self.app.test_client()

    def tearDown(self) -> None:
        self.tmp_dir.cleanup()

    def test_health_returns_json_with_all_keys(self) -> None:
        """AC1: GET /health endpoint returns JSON with keys: status, scrapers, last_run."""
        resp = self.client.get("/health")
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert "status" in data
        assert "scrapers" in data
        assert "last_run" in data

    def test_health_status_always_ok(self) -> None:
        """AC2: status field always returns 'ok'."""
        resp = self.client.get("/health")
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data["status"] == "ok"

    def test_health_scrapers_count_from_get_scraper_count(self) -> None:
        """AC3: scrapers field returns count from get_scraper_count()."""
        # init_database seeds 5 competitors
        resp = self.client.get("/health")
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data["scrapers"] == 5

    def test_health_last_run_from_get_last_run_timestamp(self) -> None:
        """AC4: last_run field returns timestamp from get_last_run_timestamp()."""
        # Insert a scrape into prices_v2
        timestamp = datetime.now(UTC).isoformat()
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO prices_v2 (competitor_id, scrape_date, scraped_at, main_price, currency) VALUES (1, ?, ?, 99.0, 'USD')",
                (datetime.now(UTC).date().isoformat(), timestamp),
            )

        resp = self.client.get("/health")
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data["last_run"] == timestamp

    def test_health_last_run_null_when_no_scrapes(self) -> None:
        """AC4 edge case: last_run is null when no scrapes exist."""
        resp = self.client.get("/health")
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data["last_run"] is None

    def test_health_endpoint_in_public_routes(self) -> None:
        """AC5: /health endpoint remains in _PUBLIC_ROUTES (unauthenticated)."""
        # Should be accessible without logging in
        resp = self.client.get("/health")
        assert resp.status_code == 200
        # Should not redirect to login
        assert resp.request.path == "/health"

    def test_health_handles_database_errors_gracefully(self) -> None:
        """AC6: Tests for updated health endpoint pass (error handling)."""
        # Close the database to force an error
        import os
        os.remove(self.db_path)
        
        # Should still return status ok with null values
        resp = self.client.get("/health")
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data["status"] == "ok"
        assert data["scrapers"] is None
        assert data["last_run"] is None

    def test_health_scrapers_zero_when_competitors_empty(self) -> None:
        """Edge case: scrapers count is 0 when competitors table is empty."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM competitors")
        
        resp = self.client.get("/health")
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data["scrapers"] == 0

    def test_health_last_run_picks_most_recent_across_tables(self) -> None:
        """Edge case: last_run returns the most recent timestamp across all scraping tables."""
        now = datetime.now(UTC)
        old_timestamp = now.replace(hour=10).isoformat()
        recent_timestamp = now.replace(hour=14).isoformat()
        
        with sqlite3.connect(self.db_path) as conn:
            # Insert old timestamp in prices_v2
            conn.execute(
                "INSERT INTO prices_v2 (competitor_id, scrape_date, scraped_at, main_price, currency) VALUES (1, ?, ?, 99.0, 'USD')",
                (now.date().isoformat(), old_timestamp),
            )
            # Insert recent timestamp in reviews_trustpilot
            conn.execute(
                "INSERT INTO reviews_trustpilot (competitor_id, scrape_date, scraped_at, overall_rating, total_reviews, source_url) VALUES (1, ?, ?, 4.5, 100, 'https://example.com')",
                (now.date().isoformat(), recent_timestamp),
            )
        
        resp = self.client.get("/health")
        assert resp.status_code == 200
        data = json.loads(resp.data)
        # Should return the most recent timestamp
        assert data["last_run"] == recent_timestamp
