# SPDX-License-Identifier: Apache-2.0
"""Security headers, the cross-site request check and the Content-Security-Policy."""

from __future__ import annotations

import base64
import hashlib
import re

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def browser(client):
    test_client = TestClient(client.app, raise_server_exceptions=False)
    test_client.auth = client.auth
    return test_client


def test_every_answer_carries_the_security_headers(browser):
    for path in ("", "api/datasets", "static/js/main.js", "login"):
        headers = browser.get(path).headers
        assert headers["x-content-type-options"] == "nosniff"
        assert headers["referrer-policy"] == "no-referrer"
        assert headers["x-frame-options"] == "SAMEORIGIN"
        assert "default-src 'self'" in headers["content-security-policy"]


def test_the_policy_allows_exactly_the_inline_script_of_the_page(browser, repo_root):
    page = (repo_root / "src/j_forecast_board/static/index.html").read_text(encoding="utf-8")
    inline = re.findall(r"<script>(.*?)</script>", page, re.S)
    assert len(inline) == 1
    digest = base64.b64encode(hashlib.sha256(inline[0].encode()).digest()).decode()
    policy = browser.get("").headers["content-security-policy"]
    assert f"'sha256-{digest}'" in policy
    assert "unsafe-eval" not in policy


def test_manuals_have_no_inline_scripts_or_handlers(repo_root):
    for name in ("index.html", "en.html"):
        page = (repo_root / "src/j_forecast_board/static/manual" / name).read_text(encoding="utf-8")
        assert not re.search(r"<script>", page)
        assert not re.search(r"\son[a-z]+=", page)


def test_a_change_sent_from_another_site_is_refused(browser):
    response = browser.post("api/assistant/deactivate", headers={"Sec-Fetch-Site": "cross-site"})
    assert response.status_code == 403
    response = browser.post("api/assistant/deactivate", headers={"Origin": "https://evil.example"})
    assert response.status_code == 403


def test_the_app_own_pages_and_scripts_may_change_things(browser):
    assert (
        browser.post(
            "api/assistant/deactivate", headers={"Sec-Fetch-Site": "same-origin"}
        ).status_code
        == 200
    )
    assert (
        browser.post(
            "api/assistant/deactivate", headers={"Origin": "http://testserver"}
        ).status_code
        == 200
    )
    assert browser.post("api/assistant/deactivate").status_code == 200  # curl and scripts


def test_reading_is_never_blocked_by_the_cross_site_check(browser):
    assert browser.get("api/datasets", headers={"Sec-Fetch-Site": "cross-site"}).status_code == 200
