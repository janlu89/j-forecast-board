# SPDX-License-Identifier: Apache-2.0
"""Audit log: one JSON line per event in logs/audit.jsonl, rotated by size.

It records what happened (sign-ins, uploads, assistant settings, consents, every call to an external
AI), never prompts, data values or keys. Writing never fails the caller.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from datetime import UTC, datetime
from pathlib import Path

MAX_BYTES = 5 * 1024 * 1024
KEEP = 3  # audit.jsonl.1 ... .3
log = logging.getLogger("j_forecast_board")
FORBIDDEN_FIELDS = {"prompt", "question", "password", "api_key", "key", "values", "text"}


class JsonlAuditLog:
    def __init__(self, path: Path, app_version: str):
        self.path = Path(path)
        self._version = app_version
        self._lock = threading.Lock()

    def record(self, event: str, **fields) -> None:
        try:
            line = dict(
                time=datetime.now(UTC).isoformat(timespec="seconds"),
                event=event,
                app_version=self._version,
                **{k: v for k, v in fields.items() if k not in FORBIDDEN_FIELDS},
            )
            with self._lock:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                self._rotate()
                with open(self.path, "a", encoding="utf-8") as handle:
                    handle.write(json.dumps(line, ensure_ascii=False, default=str) + "\n")
        except Exception:  # the audit log must never break the action it records
            log.exception("Could not write the audit log")

    def recent(self, limit: int = 200) -> list[dict]:
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()[-limit:]
        except FileNotFoundError:
            return []
        return [json.loads(line) for line in lines if line.strip()]

    def _rotate(self) -> None:
        if not self.path.exists() or self.path.stat().st_size < MAX_BYTES:
            return
        for index in range(KEEP, 0, -1):
            older = self.path.with_name(f"{self.path.name}.{index}")
            newer = self.path.with_name(f"{self.path.name}.{index - 1}") if index > 1 else self.path
            if newer.exists():
                os.replace(newer, older)
