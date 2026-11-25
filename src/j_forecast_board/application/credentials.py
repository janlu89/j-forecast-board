# SPDX-License-Identifier: Apache-2.0
"""The sign-in account: a password stored only as a scrypt hash, and signed session cookies.

At the first start a random password is generated, shown once and kept in a separate file
(initial-password.txt) until the first successful sign-in, then that file is deleted.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import threading
import time
from typing import Protocol

DEFAULT_USER = "admin"
CREDENTIALS = "credentials.json"
SESSION_KEY = "session.key"
INITIAL_PASSWORD = "initial-password.txt"
SCRYPT = dict(n=2**14, r=8, p=1)  # about 16 MB and 50 ms per check: slow to guess, fast enough
MIN_PASSWORD_LENGTH = 10


class SecretStore(Protocol):
    """Named secret values kept in files that only the user can read."""

    def get(self, name: str) -> str | None: ...

    def set(self, name: str, value: str) -> None: ...

    def delete(self, name: str) -> None: ...


class Credentials:
    def __init__(self, secrets_store: SecretStore):
        self._store = secrets_store
        self._lock = threading.Lock()
        self._account = self._load_or_create()
        self._key = self._session_key()

    # ------------------------------------------------------------------ account
    @property
    def user(self) -> str:
        return self._account["user"]

    @property
    def initial_password_pending(self) -> bool:
        return self._store.get(INITIAL_PASSWORD) is not None

    def check(self, user: str, password: str) -> bool:
        """Constant-time check of both values, so timing does not tell which one was wrong."""
        account = self._account
        expected = bytes.fromhex(account["hash"])
        given = _hash(password, bytes.fromhex(account["salt"]), account["params"])
        same_user = secrets.compare_digest(user.encode(), account["user"].encode())
        same_password = hmac.compare_digest(given, expected)
        if same_user and same_password and self.initial_password_pending:
            self._store.delete(INITIAL_PASSWORD)
        return same_user and same_password

    def set_password(self, password: str, user: str | None = None) -> None:
        """Replace the password; every open session ends (a new signing key)."""
        if len(password) < MIN_PASSWORD_LENGTH:
            raise ValueError(f"The password needs at least {MIN_PASSWORD_LENGTH} characters.")
        with self._lock:
            self._account = _account(user or self.user, password)
            self._store.set(CREDENTIALS, json.dumps(self._account))
            self._store.delete(INITIAL_PASSWORD)
            self._key = self._new_session_key()

    # ------------------------------------------------------------------ sessions
    def session(self, expires: int) -> str:
        return f"{expires}.{self._sign(expires)}"

    def session_valid(self, value: str | None) -> bool:
        if not value or "." not in value:
            return False
        expires, _, signature = value.partition(".")
        if not expires.isdigit() or int(expires) <= time.time():
            return False
        return hmac.compare_digest(signature, self._sign(int(expires)))

    def _sign(self, expires: int) -> str:
        return hmac.new(self._key, str(expires).encode(), hashlib.sha256).hexdigest()

    # ------------------------------------------------------------------ storage
    def _load_or_create(self) -> dict:
        stored = self._store.get(CREDENTIALS)
        if stored is None:
            password = secrets.token_urlsafe(12)
            account = _account(DEFAULT_USER, password)
            self._store.set(CREDENTIALS, json.dumps(account))
            self._store.set(INITIAL_PASSWORD, password + "\n")
            print(
                f"[auth] First start: sign in as '{DEFAULT_USER}' with password '{password}'. "
                f"It is also in secrets/{INITIAL_PASSWORD} until the first sign-in.",
                flush=True,
            )
            return account
        data = json.loads(stored)
        if "password" in data:  # older install: plain text password, hash it now
            account = _account(
                data.get("utente") or data.get("user") or DEFAULT_USER, data["password"]
            )
            self._store.set(CREDENTIALS, json.dumps(account))
            return account
        return data

    def _session_key(self) -> bytes:
        stored = self._store.get(SESSION_KEY)
        return bytes.fromhex(stored.strip()) if stored else self._new_session_key()

    def _new_session_key(self) -> bytes:
        key = secrets.token_bytes(32)
        self._store.set(SESSION_KEY, key.hex())
        return key


def _account(user: str, password: str) -> dict:
    salt = secrets.token_bytes(16)
    return dict(user=user, salt=salt.hex(), hash=_hash(password, salt, SCRYPT).hex(), params=SCRYPT)


def _hash(password: str, salt: bytes, params: dict) -> bytes:
    return hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=params["n"], r=params["r"], p=params["p"], dklen=32
    )
