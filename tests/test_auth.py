"""Tests for S-12: basic auth on the dashboard."""
from __future__ import annotations

import os
from pathlib import Path

import pytest
from flask.testing import FlaskClient

from dashboard.server import create_app
from init_db import init_database


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> FlaskClient:
    monkeypatch.setenv("DASHBOARD_PASSWORD", "testpass")
    db_path = tmp_path / "test_auth.db"
    init_database(db_path)
    app = create_app(db_path)
    app.testing = True
    return app.test_client()


# ---------------------------------------------------------------------------
# Login page
# ---------------------------------------------------------------------------


def test_login_page_returns_200(client: FlaskClient) -> None:
    resp = client.get("/login")
    assert resp.status_code == 200


def test_login_page_contains_form(client: FlaskClient) -> None:
    data: bytes = client.get("/login").data
    html = data.decode()
    assert "<form" in html
    assert 'type="password"' in html
    assert 'action="/login"' in html


def test_login_page_no_error_by_default(client: FlaskClient) -> None:
    data: bytes = client.get("/login").data
    html = data.decode()
    # Error div should not be rendered when no error is present
    assert "Incorrect password" not in html


# ---------------------------------------------------------------------------
# Unauthenticated access redirects to /login
# ---------------------------------------------------------------------------


def test_root_redirects_to_login_when_unauthenticated(client: FlaskClient) -> None:
    resp = client.get("/")
    assert resp.status_code == 302
    location: str = resp.headers.get("Location", "")
    assert "/login" in location


def test_api_prices_redirects_to_login_when_unauthenticated(client: FlaskClient) -> None:
    resp = client.get("/api/prices")
    assert resp.status_code == 302
    location: str = resp.headers.get("Location", "")
    assert "/login" in location


def test_api_products_redirects_to_login_when_unauthenticated(client: FlaskClient) -> None:
    resp = client.get("/api/products")
    assert resp.status_code == 302


def test_api_reviews_redirects_to_login_when_unauthenticated(client: FlaskClient) -> None:
    resp = client.get("/api/reviews")
    assert resp.status_code == 302


def test_api_diffs_redirects_to_login_when_unauthenticated(client: FlaskClient) -> None:
    resp = client.get("/api/diffs")
    assert resp.status_code == 302


def test_api_ab_tests_redirects_to_login_when_unauthenticated(client: FlaskClient) -> None:
    resp = client.get("/api/ab-tests")
    assert resp.status_code == 302


def test_api_competitors_redirects_to_login_when_unauthenticated(client: FlaskClient) -> None:
    resp = client.get("/api/competitors")
    assert resp.status_code == 302


# ---------------------------------------------------------------------------
# /health is publicly accessible (no auth required)
# ---------------------------------------------------------------------------


def test_health_accessible_without_auth(client: FlaskClient) -> None:
    resp = client.get("/health")
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Login with correct password
# ---------------------------------------------------------------------------


def test_correct_password_redirects_to_root(client: FlaskClient) -> None:
    resp = client.post("/login", data={"password": "testpass"})
    assert resp.status_code == 302
    location: str = resp.headers.get("Location", "")
    assert location == "/" or location.endswith("/")


def test_correct_password_grants_access_to_root(client: FlaskClient) -> None:
    # Login first
    client.post("/login", data={"password": "testpass"})
    # Now access root
    resp = client.get("/")
    assert resp.status_code == 200


def test_correct_password_grants_access_to_api(client: FlaskClient) -> None:
    client.post("/login", data={"password": "testpass"})
    resp = client.get("/api/prices")
    assert resp.status_code == 200


def test_correct_password_grants_access_to_competitors(client: FlaskClient) -> None:
    client.post("/login", data={"password": "testpass"})
    resp = client.get("/api/competitors")
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Login with wrong password
# ---------------------------------------------------------------------------


def test_wrong_password_returns_200_with_error(client: FlaskClient) -> None:
    resp = client.post("/login", data={"password": "wrongpassword"})
    assert resp.status_code == 200


def test_wrong_password_shows_error_message(client: FlaskClient) -> None:
    resp = client.post("/login", data={"password": "wrongpassword"})
    data: bytes = resp.data
    html = data.decode()
    assert "Incorrect password" in html


def test_wrong_password_does_not_grant_session(client: FlaskClient) -> None:
    client.post("/login", data={"password": "wrongpassword"})
    # Should still be redirected (unauthenticated)
    resp = client.get("/api/prices")
    assert resp.status_code == 302


def test_empty_password_does_not_authenticate(client: FlaskClient) -> None:
    client.post("/login", data={"password": ""})
    resp = client.get("/")
    assert resp.status_code == 302


# ---------------------------------------------------------------------------
# Logout
# ---------------------------------------------------------------------------


def test_logout_clears_session(client: FlaskClient) -> None:
    # Login
    client.post("/login", data={"password": "testpass"})
    # Verify logged in
    assert client.get("/api/prices").status_code == 200
    # Logout
    client.get("/logout")
    # Should redirect again after logout
    resp = client.get("/api/prices")
    assert resp.status_code == 302


def test_logout_redirects_to_login(client: FlaskClient) -> None:
    client.post("/login", data={"password": "testpass"})
    resp = client.get("/logout")
    assert resp.status_code == 302
    location: str = resp.headers.get("Location", "")
    assert "/login" in location


# ---------------------------------------------------------------------------
# Password from environment variable
# ---------------------------------------------------------------------------


def test_password_read_from_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DASHBOARD_PASSWORD", "env-password-xyz")
    db_path = tmp_path / "env_auth.db"
    init_database(db_path)
    app = create_app(db_path)
    app.testing = True
    c = app.test_client()

    # Wrong password
    c.post("/login", data={"password": "wrongpass"})
    assert c.get("/api/prices").status_code == 302

    # Correct env password
    c2 = app.test_client()
    c2.post("/login", data={"password": "env-password-xyz"})
    assert c2.get("/api/prices").status_code == 200


def test_default_password_is_changeme(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DASHBOARD_PASSWORD", raising=False)
    db_path = tmp_path / "default_auth.db"
    init_database(db_path)
    app = create_app(db_path)
    app.testing = True
    c = app.test_client()

    c.post("/login", data={"password": "changeme"})
    assert c.get("/api/prices").status_code == 200
