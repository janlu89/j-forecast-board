# SPDX-License-Identifier: Apache-2.0
"""The on-disk cache of backtest results survives crashes and bad files."""

from __future__ import annotations

import numpy as np
import pytest

from j_forecast_board import engine, evaluate

VARIANT = "mistralai/Timestral-28M|cov|missing"


@pytest.fixture
def cache(monkeypatch, tmp_path, make_dataset):
    monkeypatch.setattr(evaluate, "RESULTS_DIR", tmp_path)
    monkeypatch.setattr(evaluate, "MEMO", {})
    return make_dataset(np.arange(30.0))


def test_file_name_uses_the_model_not_its_display_label(cache, monkeypatch):
    stub_names = {repo: f"{name} · stub" for repo, name in engine.MODELS.items()}
    monkeypatch.setattr(engine, "MODELS", stub_names)
    assert evaluate._path(cache, 12, 0, VARIANT).name == "H12_L0_Timestral-28M_cov_missing.npz"


def test_an_unreadable_cache_file_is_dropped_instead_of_crashing(cache, capsys):
    path = evaluate._path(cache, 4, 0, VARIANT)
    path.parent.mkdir(parents=True)
    path.write_bytes(b"PK\x03\x04 truncated")
    assert evaluate.get_result(cache, 4, 0, VARIANT) is None
    assert not path.exists()
    assert "computed again" in capsys.readouterr().out


def test_saving_is_atomic(cache, monkeypatch):
    path = evaluate._path(cache, 4, 0, VARIANT)

    def crash_while_writing(target, **arrays):
        target.write(b"partial")
        raise KeyboardInterrupt

    monkeypatch.setattr(np, "savez_compressed", crash_while_writing)
    with pytest.raises(KeyboardInterrupt):
        evaluate._save(path, {"a": np.zeros(2)})
    assert list(path.parent.iterdir()) == []


def test_a_saved_result_reads_back(cache):
    path = evaluate._path(cache, 4, 0, VARIANT)
    evaluate._save(path, {"a": np.arange(3), "meta": '{"total_v": 2}'})
    with np.load(path) as stored:
        assert stored["a"].tolist() == [0, 1, 2]
