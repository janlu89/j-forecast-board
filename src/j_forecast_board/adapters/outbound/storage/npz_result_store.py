# SPDX-License-Identifier: Apache-2.0
"""Backtest results as compressed .npz files, one folder per dataset (implements ResultStore)."""

from __future__ import annotations

import io
import json
import os
import shutil
import zipfile
import zlib
from pathlib import Path

import numpy as np

from ....application.ports import BacktestResult
from ....domain.forecast import QUANTILE_LEVELS, ModelVariant, short_model_name
from ....domain.series import Dataset

ARRAYS = ("bt", "fut", "cuts", "secs", "secs_total", "total_bt", "total_fut")


class NpzResultStore:
    def __init__(self, folder: Path):
        self.folder = Path(folder)

    def path(self, ds: Dataset, horizon: int, context: int, variant_key: str) -> Path:
        variant = ModelVariant.parse(variant_key)
        covariates = "cov" if variant.use_covariates else "nocov"
        closed = "zero" if variant.closed_as_zero else "missing"
        name = f"H{horizon}_L{context}_{short_model_name(variant.repo)}_{covariates}_{closed}.npz"
        return self.folder / ds.key / name

    def find(
        self, ds: Dataset, horizon: int, context: int, variant_key: str
    ) -> BacktestResult | None:
        path = self.path(ds, horizon, context, variant_key)
        if not ds.persist or not path.exists():
            return None
        try:
            # Read the bytes first: a file numpy cannot parse stays open otherwise, and Windows
            # refuses to delete an open file.
            with np.load(io.BytesIO(path.read_bytes()), allow_pickle=False) as stored:
                arrays = {name: stored[name] for name in stored.files}
            return _result(arrays)
        except (zipfile.BadZipFile, zlib.error, ValueError, KeyError, EOFError, OSError) as error:
            print(
                f"[warn] cached result {path.name} is unreadable ({type(error).__name__}); "
                "it will be computed again.",
                flush=True,
            )
            path.unlink(missing_ok=True)
            return None

    def save(
        self, ds: Dataset, horizon: int, context: int, variant_key: str, result: BacktestResult
    ) -> None:
        if not ds.persist:
            return
        arrays = {
            name: getattr(result, name) for name in ARRAYS if getattr(result, name) is not None
        }
        arrays["meta"] = json.dumps(result.meta)
        arrays["levels"] = np.asarray(result.levels)
        _write_atomically(self.path(ds, horizon, context, variant_key), arrays)

    def delete_for(self, ds: Dataset) -> None:
        shutil.rmtree(self.folder / ds.key, ignore_errors=True)


def _result(arrays: dict) -> BacktestResult:
    levels = tuple(float(x) for x in arrays["levels"]) if "levels" in arrays else QUANTILE_LEVELS
    return BacktestResult(
        bt=arrays["bt"],
        fut=arrays["fut"],
        cuts=arrays["cuts"],
        secs=float(arrays["secs"]),
        secs_total=float(arrays["secs_total"]),
        meta=json.loads(str(arrays["meta"])),
        total_bt=arrays.get("total_bt"),
        total_fut=arrays.get("total_fut"),
        levels=levels,
    )


def _write_atomically(path: Path, arrays: dict) -> None:
    """Stopping the app mid-write never leaves a truncated cache file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    try:
        with open(temporary, "wb") as handle:
            np.savez_compressed(handle, **arrays)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
