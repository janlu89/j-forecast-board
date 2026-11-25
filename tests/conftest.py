# SPDX-License-Identifier: Apache-2.0
"""Test session setup: every test runs against a scratch runtime folder, never the real one.

The environment is prepared at import time, before any test module imports the app, because the
legacy modules read JFB_HOME and the credentials file when they are imported.
"""

from __future__ import annotations

import json
import os
import secrets
import shutil
import tempfile
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "golden" / "fixtures"

SCRATCH_HOME = Path(tempfile.mkdtemp(prefix="jfb-test-"))
shutil.copytree(FIXTURES, SCRATCH_HOME, dirs_exist_ok=True)

TEST_USER = "tester"
TEST_PASSWORD = secrets.token_urlsafe(16)
(SCRATCH_HOME / "secrets").mkdir()
(SCRATCH_HOME / "secrets" / "credentials.json").write_text(
    json.dumps({"utente": TEST_USER, "password": TEST_PASSWORD}), encoding="utf-8"
)

os.environ["JFB_HOME"] = str(SCRATCH_HOME)
os.environ["HF_HUB_OFFLINE"] = "1"  # tests never download weights


@pytest.fixture(scope="session")
def credentials() -> tuple[str, str]:
    """User name and password of the scratch install."""
    return TEST_USER, TEST_PASSWORD


@pytest.fixture(scope="session")
def scratch_home() -> Path:
    return SCRATCH_HOME


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def pytest_sessionfinish(session, exitstatus):
    shutil.rmtree(SCRATCH_HOME, ignore_errors=True)
