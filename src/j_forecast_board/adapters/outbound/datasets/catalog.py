# SPDX-License-Identifier: Apache-2.0
"""The datasets the app knows: the built-in public ones plus the user's uploads (in memory)."""

from __future__ import annotations

import threading
from collections.abc import Callable

from ....domain.errors import NotFound
from ....domain.series import Dataset
from .builtin import bike, energy, germany, melbourne, passengers, rossmann
from .downloader import Downloader

Loader = Callable[[Downloader], Dataset]
BUILTIN_LOADERS: dict[str, Loader] = {
    "rossmann": rossmann.load,
    "bike": bike.load,
    "energy": energy.load,
    "passengers": passengers.load,
    "germany": germany.load,
    "melbourne": melbourne.load,
}


class InMemoryCatalog:
    def __init__(self, downloader: Downloader, loaders: dict[str, Loader] | None = None):
        self._downloader = downloader
        self._loaders = BUILTIN_LOADERS if loaders is None else loaders
        self._datasets: dict[str, Dataset] = {}
        self._lock = threading.Lock()

    def load_builtin(self) -> list[str]:
        """Load every built-in dataset; one that fails is skipped so the app stays usable."""
        problems = []
        for name, load in self._loaders.items():
            try:
                ds = load(self._downloader)
            except Exception as error:  # a failed download must not stop the start
                problems.append(f"{name}: {error}")
                print(f"[warn] dataset {name} not loaded: {error}", flush=True)
                continue
            self.register(ds)
            print(f"[data] {ds.key}: {ds.N} series x {ds.T} points", flush=True)
        return problems

    def list(self) -> list[Dataset]:
        with self._lock:
            return list(self._datasets.values())

    def get(self, key: str) -> Dataset:
        with self._lock:
            if key not in self._datasets:
                raise NotFound(f"Unknown dataset {key}")
            return self._datasets[key]

    def register(self, ds: Dataset) -> None:
        with self._lock:
            self._datasets[ds.key] = ds

    def remove(self, key: str) -> None:
        with self._lock:
            if self._datasets.pop(key, None) is None:
                raise NotFound(f"Unknown dataset {key}")
