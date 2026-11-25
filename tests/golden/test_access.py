# SPDX-License-Identifier: Apache-2.0
"""How the current app protects its routes (login page, session cookie, Basic auth)."""

from __future__ import annotations

from fastapi.testclient import TestClient


def anonymous(client) -> TestClient:
    """A second client on the same app, without credentials or cookies."""
    return TestClient(client.app, follow_redirects=False)


def test_api_without_credentials_is_refused(client):
    response = anonymous(client).get("api/datasets")
    assert response.status_code == 401
    assert response.json() == {"error": "Login required"}


def test_browser_without_session_is_sent_to_the_login_page(client):
    response = anonymous(client).get("static/app.js", headers={"accept": "text/html"})
    assert response.status_code == 303
    assert response.headers["location"] == "../login?next=static/app.js"


def test_login_page_is_public(client):
    response = anonymous(client).get("login")
    assert response.status_code == 200
    assert 'name="password"' in response.text


def test_wrong_password_returns_to_the_login_page(client, credentials):
    user, _ = credentials
    form = {"username": user, "password": "wrong", "next": "static/app.js"}
    response = anonymous(client).post("login", data=form)
    assert response.status_code == 303
    assert response.headers["location"] == "login?e=1&next=static/app.js"


def test_login_sets_a_session_cookie_that_opens_the_api(client, credentials):
    user, password = credentials
    browser = anonymous(client)
    response = browser.post("login", data={"username": user, "password": password, "next": ""})
    assert response.status_code == 303
    assert response.headers["location"] == "./"
    assert "timestral_session" in response.cookies
    assert browser.get("api/datasets").status_code == 200


def test_index_versions_its_own_assets(client):
    response = client.get("")
    assert response.status_code == 200
    assert '"static/app.js?v=' in response.text
    assert '"static/style.css?v=' in response.text
    assert response.headers["cache-control"] == "no-store"
