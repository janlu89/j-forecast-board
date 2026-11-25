# SPDX-License-Identifier: Apache-2.0
"""Doctor checks and the report they produce (docs/ROADMAP.md, Appendix F).

The report is meant to be read by someone else, so it never contains secrets, data values, the
user's name or the values of environment variables: paths under the user's home are shown as `~`.
"""

from __future__ import annotations

import getpass
import json
import time
from collections import Counter
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

OK, WARN, FAIL = "ok", "warn", "fail"
SCHEMA_VERSION = 1
_SEVERITY = {FAIL: 0, WARN: 1, OK: 2}


@dataclass
class Check:
    id: str
    group: str
    status: str
    message: str
    fix: str = ""
    details: dict = field(default_factory=dict)
    duration_ms: int = 0


def run_check(group: str, check_id: str, probe: Callable[[], Check]) -> Check:
    """Run one probe, time it, and turn an unexpected exception into a failed check."""
    started = time.perf_counter()
    try:
        check = probe()
    except Exception as error:  # a broken probe must not stop the other checks
        check = Check(check_id, group, FAIL, f"{type(error).__name__}: {error}")
    check.id, check.group = check_id, group
    check.duration_ms = round((time.perf_counter() - started) * 1000)
    return check


class Redactor:
    """Hide the user's home folder and user name in everything the report says."""

    def __init__(self, home: Path | None = None, user: str | None = None):
        self._home = str(home or Path.home())
        try:
            self._user = user if user is not None else getpass.getuser()
        except Exception:  # no user name available (some service accounts)
            self._user = ""

    def text(self, value: str) -> str:
        value = value.replace(self._home, "~")
        if len(self._user) >= 3:
            value = value.replace(self._user, "<user>")
        return value

    def value(self, value):
        if isinstance(value, str):
            return self.text(value)
        if isinstance(value, dict):
            return {key: self.value(item) for key, item in value.items()}
        if isinstance(value, list | tuple):
            return [self.value(item) for item in value]
        return value


@dataclass
class Report:
    mode: str
    app_version: str
    commit: str
    checks: list[Check] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat(timespec="seconds"))

    @property
    def summary(self) -> dict[str, int]:
        counts = Counter(check.status for check in self.checks)
        return {status: counts.get(status, 0) for status in (OK, WARN, FAIL)}

    @property
    def exit_code(self) -> int:
        return 1 if self.summary[FAIL] else 0

    def to_dict(self, redactor: Redactor) -> dict:
        return redactor.value(
            dict(
                schema_version=SCHEMA_VERSION,
                app_version=self.app_version,
                commit=self.commit,
                created_at=self.created_at,
                mode=self.mode,
                summary=self.summary,
                checks=[asdict(check) for check in self.checks],
            )
        )

    def to_text(self, redactor: Redactor) -> str:
        data = self.to_dict(redactor)
        summary = data["summary"]
        lines = [
            f"J-Forecast Board doctor report ({data['mode']})",
            f"version {data['app_version']}, commit {data['commit']}, {data['created_at']}",
            f"ok {summary[OK]}, warnings {summary[WARN]}, failures {summary[FAIL]}",
        ]
        ordered = sorted(data["checks"], key=lambda c: (_SEVERITY[c["status"]], c["group"]))
        group = None
        for check in ordered:
            if check["group"] != group:
                group = check["group"]
                lines += ["", f"[{group}]"]
            lines.append(f"  {check['status'].upper():4} {check['id']}: {check['message']}")
            if check["fix"] and check["status"] != OK:
                lines.append(f"       fix: {check['fix']}")
        return "\n".join(lines) + "\n"

    def write(self, folder: Path, redactor: Redactor) -> tuple[Path, Path]:
        folder.mkdir(parents=True, exist_ok=True)
        json_path, text_path = folder / "doctor-report.json", folder / "doctor-report.txt"
        json_path.write_text(
            json.dumps(self.to_dict(redactor), indent=1, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        text_path.write_text(self.to_text(redactor), encoding="utf-8")
        return json_path, text_path
