# SPDX-License-Identifier: Apache-2.0
"""The user's own CSV: read it, show what was found, register it as a private dataset."""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from typing import Protocol

from ..domain.errors import InvalidRequest, NotFound
from ..domain.series import Dataset
from .view_model import dataset_meta
from .workbench import Workbench

MAX_UPLOAD_BYTES = 200 * 1024 * 1024


@dataclass(frozen=True)
class UploadSpec:
    """How to read an uploaded table: which columns are dates, target, series id and covariates."""

    uid: str
    date_col: str
    target: str
    id_col: str | None = None
    past: list[str] = field(default_factory=list)
    known: list[str] = field(default_factory=list)
    cat: list[str] = field(default_factory=list)
    freq: str | None = None
    season: int | None = None
    horizon: int | None = None
    calendar: bool = True
    country: str | None = None
    name: str | None = None
    agg: str = "sum"


class TableReader(Protocol):
    def parse(self, raw: bytes) -> object:
        """Read a CSV (any separator, European decimals) into a table."""
        ...

    def preview(self, table: object) -> dict:
        """Rows, columns, guessed roles of the columns, the first rows as text."""
        ...

    def build(self, table: object, spec: UploadSpec, key: str) -> Dataset:
        """Turn the table into a private dataset."""
        ...


class Uploads:
    """Uploaded tables waiting to be registered; they stay in memory only."""

    def __init__(
        self,
        reader: TableReader,
        workbench: Workbench,
        max_bytes: int = MAX_UPLOAD_BYTES,
        audit=None,
    ):
        self._audit = audit
        self._reader = reader
        self._workbench = workbench
        self._max_bytes = max_bytes
        self._pending: dict[str, object] = {}
        self._lock = threading.Lock()

    def preview(self, raw: bytes, filename: str | None) -> dict:
        if len(raw) > self._max_bytes:
            raise InvalidRequest(f"File larger than {self._max_bytes // (1024 * 1024)} MB.")
        table = self._reader.parse(raw)
        uid = uuid.uuid4().hex[:8]
        with self._lock:
            self._pending[uid] = table
        return dict(uid=uid, name=filename, **self._reader.preview(table))

    def register(self, spec: UploadSpec) -> dict:
        with self._lock:
            table = self._pending.get(spec.uid)
        if table is None:
            raise NotFound("This upload has expired: please upload the file again.")
        ds = self._reader.build(table, spec, key=f"up_{spec.uid}")
        self._workbench.catalog.register(ds)
        first = self._workbench.default_variants(ds)[0]
        self._workbench.evaluations.submit(ds, ds.horizon, ds.context, first)
        if self._audit is not None:
            self._audit.record(
                "dataset_uploaded", dataset=ds.key, rows=ds.T, series=ds.N, columns=1 + len(ds.covs)
            )
        return dataset_meta(ds)

    def forget(self, key: str) -> None:
        """Delete an uploaded dataset and everything computed from it."""
        ds = self._workbench.catalog.get(key)
        if not ds.is_private:
            raise InvalidRequest("Built-in datasets cannot be deleted.")
        self._workbench.catalog.remove(key)
        self._workbench.evaluations.forget(ds)
        with self._lock:
            self._pending.pop(key.removeprefix("up_"), None)
        if self._audit is not None:
            self._audit.record("dataset_deleted", dataset=key)
