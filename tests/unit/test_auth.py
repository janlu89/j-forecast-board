# SPDX-License-Identifier: Apache-2.0
"""Session cookie signing and the redirect target filter of the login page."""

from __future__ import annotations

import base64
import time

import pytest

from j_forecast_board import auth


def test_a_signed_session_that_has_not_expired_is_valid():
    expires = int(time.time()) + 60
    assert auth._session_ok(f"{expires}.{auth._sign(expires)}")


def test_an_expired_session_is_refused():
    expires = int(time.time()) - 1
    assert not auth._session_ok(f"{expires}.{auth._sign(expires)}")


@pytest.mark.parametrize("value", [None, "", "abc", "123.deadbeef", "x.y"])
def test_malformed_or_forged_sessions_are_refused(value):
    assert not auth._session_ok(value)


def test_a_session_signed_for_another_expiry_is_refused():
    expires = int(time.time()) + 60
    assert not auth._session_ok(f"{expires + 1}.{auth._sign(expires)}")


def test_credentials_must_both_match(credentials):
    user, password = credentials
    assert auth._credentials_ok(user, password)
    assert not auth._credentials_ok(user, password + "x")
    assert not auth._credentials_ok("someone", password)


def test_basic_auth_header_is_accepted(credentials):
    user, password = credentials
    token = base64.b64encode(f"{user}:{password}".encode()).decode()
    assert auth._basic_ok(f"Basic {token}")
    assert not auth._basic_ok(f"Bearer {token}")
    assert not auth._basic_ok("Basic not-base64!")


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("/static/app.js", "static/app.js"),
        ("manual/en", "manual/en"),
        (None, ""),
        ("../etc/passwd", ""),
        ("//evil.example", "evil.example"),  # leading slashes go: stays a path inside the app
        ("https://evil.example", ""),
        ("a?b=c", ""),
        ("x" * 201, ""),
    ],
)
def test_safe_next_keeps_only_relative_app_paths(value, expected):
    assert auth._safe_next(value) == expected


@pytest.mark.parametrize(
    ("path", "prefix"), [("/", ""), ("/login", ""), ("/static/app.js", "../"), ("/a/b/c", "../../")]
)
def test_to_root_climbs_back_to_the_app_root(path, prefix):
    assert auth._to_root(path) == prefix
