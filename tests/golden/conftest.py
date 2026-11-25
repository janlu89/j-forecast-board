# SPDX-License-Identifier: Apache-2.0
"""Snapshot comparison for the golden tests (the app fixture is in tests/conftest.py).

Snapshots live in tests/golden/snapshots. To approve a new behaviour on purpose, rerun with
JFB_UPDATE_GOLDEN=1 and review the diff of the JSON files before committing it.
"""

from __future__ import annotations

import json
import math
import os
from pathlib import Path

import pytest

SNAPSHOTS = Path(__file__).parent / "snapshots"


# ----------------------------------------------------------------------------- snapshots
@pytest.fixture
def golden():
    """Compare a JSON-like value with its approved snapshot (floats with a relative tolerance)."""

    def check(name: str, value, rel: float = 1e-6, abs_tol: float = 1e-9, ignore=()) -> None:
        actual = _without_keys(json.loads(json.dumps(value)), set(ignore))
        path = SNAPSHOTS / f"{name}.json"
        if os.environ.get("JFB_UPDATE_GOLDEN") == "1":
            text = json.dumps(actual, indent=1, ensure_ascii=False) + "\n"
            path.write_text(text, encoding="utf-8")
            return
        assert path.exists(), f"no snapshot {path.name}: run once with JFB_UPDATE_GOLDEN=1"
        expected = json.loads(path.read_text(encoding="utf-8"))
        _assert_same(expected, actual, rel, abs_tol, where=name)

    return check


def _without_keys(value, ignore: set):
    if isinstance(value, dict):
        return {k: _without_keys(v, ignore) for k, v in value.items() if k not in ignore}
    if isinstance(value, list):
        return [_without_keys(v, ignore) for v in value]
    return value


def _assert_same(expected, actual, rel: float, abs_tol: float, where: str) -> None:
    if isinstance(expected, dict):
        assert isinstance(actual, dict), f"{where}: expected an object"
        assert list(expected) == list(actual), f"{where}: keys differ"
        for key in expected:
            _assert_same(expected[key], actual[key], rel, abs_tol, f"{where}.{key}")
    elif isinstance(expected, list):
        assert isinstance(actual, list), f"{where}: expected a list"
        assert len(expected) == len(actual), f"{where}: length {len(actual)} != {len(expected)}"
        for i, (e, a) in enumerate(zip(expected, actual, strict=True)):
            _assert_same(e, a, rel, abs_tol, f"{where}[{i}]")
    elif isinstance(expected, float) and isinstance(actual, (int, float)):
        assert math.isclose(expected, actual, rel_tol=rel, abs_tol=abs_tol), (
            f"{where}: {actual} != {expected}"
        )
    else:
        assert expected == actual, f"{where}: {actual!r} != {expected!r}"
