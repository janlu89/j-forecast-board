# SPDX-License-Identifier: Apache-2.0
"""Sign-in: password hashing, session signing, the redirect filter of the login page."""

from __future__ import annotations

import base64
import json
import os
import secrets
import stat
import time

import pytest

from j_forecast_board.adapters.inbound.http.auth import Authenticator, safe_next, to_root
from j_forecast_board.adapters.outbound.storage.file_secret_store import FileSecretStore
from j_forecast_board.application.credentials import Credentials


@pytest.fixture
def store(tmp_path):
    return FileSecretStore(tmp_path / "secrets")


@pytest.fixture
def credentials(store, capsys):
    made = Credentials(store)
    capsys.readouterr()
    return made


def initial_password(store) -> str:
    return store.get("initial-password.txt").strip()


def test_first_start_creates_admin_with_a_random_password_shown_once(store, capsys):
    made = Credentials(store)
    password = initial_password(store)
    printed = capsys.readouterr().out
    assert made.user == "admin" and password in printed
    assert Credentials(store).user == "admin"
    assert capsys.readouterr().out == ""


def test_the_password_is_stored_only_as_a_hash(store, credentials):
    password = initial_password(store)
    stored = store.get("credentials.json")
    assert password not in stored
    assert set(json.loads(stored)) == {"user", "salt", "hash", "params"}


@pytest.mark.skipif(os.name == "nt", reason="POSIX permissions")
def test_secret_files_are_private(store, credentials):
    for name in ("credentials.json", "session.key", "initial-password.txt"):
        assert stat.S_IMODE((store.folder / name).stat().st_mode) == 0o600


def test_check_needs_both_values(store, credentials):
    password = initial_password(store)
    assert not credentials.check("admin", password + "x")
    assert not credentials.check("someone", password)
    assert credentials.check("admin", password)


def test_the_initial_password_file_goes_away_at_the_first_sign_in(store, credentials):
    assert credentials.check("admin", initial_password(store))
    assert store.get("initial-password.txt") is None
    assert not credentials.initial_password_pending


def test_an_older_plain_text_password_is_hashed_on_first_use(store):
    password = secrets.token_urlsafe(12)
    store.set("credentials.json", json.dumps({"utente": "demo", "password": password}))
    made = Credentials(store)
    assert made.check("demo", password)
    assert password not in store.get("credentials.json")


def test_a_new_password_ends_every_session(store, credentials):
    old = credentials.session(int(time.time()) + 60)
    new_password = secrets.token_urlsafe(12)
    credentials.set_password(new_password)
    assert credentials.check("admin", new_password)
    assert not credentials.session_valid(old)


def test_short_passwords_are_refused(credentials):
    with pytest.raises(ValueError, match="at least 10"):
        credentials.set_password("short")


def test_a_signed_session_that_has_not_expired_is_valid(credentials):
    assert credentials.session_valid(credentials.session(int(time.time()) + 60))


def test_an_expired_session_is_refused(credentials):
    assert not credentials.session_valid(credentials.session(int(time.time()) - 1))


@pytest.mark.parametrize("value", [None, "", "abc", "123.deadbeef", "x.y"])
def test_malformed_or_forged_sessions_are_refused(credentials, value):
    assert not credentials.session_valid(value)


def test_a_session_signed_for_another_expiry_is_refused(credentials):
    expires = int(time.time()) + 60
    signature = credentials.session(expires).split(".")[1]
    assert not credentials.session_valid(f"{expires + 1}.{signature}")


def test_sessions_survive_a_restart(store, credentials):
    value = credentials.session(int(time.time()) + 60)
    assert Credentials(store).session_valid(value)


def test_basic_auth_header_is_accepted(store, credentials):
    password = initial_password(store)
    auth = Authenticator(credentials, enabled=True)
    token = base64.b64encode(f"admin:{password}".encode()).decode()
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
    assert safe_next(value) == expected


@pytest.mark.parametrize(
    ("path", "prefix"), [("/", ""), ("/login", ""), ("/static/app.js", "../"), ("/a/b/c", "../../")]
)
def test_to_root_climbs_back_to_the_app_root(path, prefix):
    assert to_root(path) == prefix
