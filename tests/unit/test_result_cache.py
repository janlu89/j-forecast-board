# SPDX-License-Identifier: Apache-2.0
"""The on-disk cache of backtest results survives crashes and bad files."""

from __future__ import annotations

import numpy as np
import pytest

from j_forecast_board.adapters.outbound.storage import npz_result_store as module
from j_forecast_board.adapters.outbound.storage.npz_result_store import NpzResultStore
from j_forecast_board.application.ports import BacktestResult

VARIANT = "mistralai/Timestral-28M|cov|missing"


@pytest.fixture
def ds(make_dataset):
    return make_dataset(np.arange(30.0))


def result() -> BacktestResult:
    return BacktestResult(
        bt=np.zeros((1, 2, 4, 21)), fut=np.ones((1, 4, 21)), cuts=np.array([22, 26]),
        secs=1.0, secs_total=2.0, meta={"total_v": 2},
    )  # fmt: skip


def test_file_name_uses_the_model_id(tmp_path, ds):
    path = NpzResultStore(tmp_path).path(ds, 12, 0, VARIANT)
    assert path == tmp_path / "unit" / "H12_L0_Timestral-28M_cov_missing.npz"


def test_a_saved_result_reads_back(tmp_path, ds):
    store = NpzResultStore(tmp_path)
    store.save(ds, 4, 0, VARIANT, result())
    found = store.find(ds, 4, 0, VARIANT)
    assert found.cuts.tolist() == [22, 26]
    assert found.meta == {"total_v": 2}
    assert found.total_bt is None
    assert len(found.levels) == 21


def test_an_unreadable_cache_file_is_dropped_instead_of_crashing(tmp_path, ds, capsys):
    store = NpzResultStore(tmp_path)
    path = store.path(ds, 4, 0, VARIANT)
    path.parent.mkdir(parents=True)
    path.write_bytes(b"PK\x03\x04 truncated")
    assert store.find(ds, 4, 0, VARIANT) is None
    assert not path.exists()
    assert "computed again" in capsys.readouterr().out


def test_saving_is_atomic(tmp_path, ds, monkeypatch):
    store = NpzResultStore(tmp_path)

    def crash_while_writing(target, **arrays):
        target.write(b"partial")
        raise KeyboardInterrupt

    monkeypatch.setattr(module.np, "savez_compressed", crash_while_writing)
    with pytest.raises(KeyboardInterrupt):
        store.save(ds, 4, 0, VARIANT, result())
    assert list(store.path(ds, 4, 0, VARIANT).parent.iterdir()) == []


def test_datasets_that_must_not_persist_are_not_written(tmp_path, make_dataset):
    private = make_dataset(np.arange(30.0), persist=False)
    store = NpzResultStore(tmp_path)
    store.save(private, 4, 0, VARIANT, result())
    assert not any(tmp_path.iterdir())
