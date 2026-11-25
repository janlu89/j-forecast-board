# SPDX-License-Identifier: Apache-2.0
"""Settings without secrets as a JSON file, written atomically; and the read-only admin policy."""

from __future__ import annotations

import json
import os
from pathlib import Path

from ....application.policy import Policy, PolicyError


class JsonSettingsStore:
    def __init__(self, path: Path):
        self.path = Path(path)

    def load(self) -> dict:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (FileNotFoundError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def save(self, data: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(self.path.name + ".tmp")
        temporary.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
        os.replace(temporary, self.path)


def load_policy(path: Path) -> Policy:
    """The admin policy, or the defaults when there is no file. A broken file stops the start."""
    if not path.exists():
        return Policy()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as error:
        raise PolicyError(f"The policy file {path} is not valid JSON: {error}") from None
    if not isinstance(data, dict):
        raise PolicyError(f"The policy file {path} must contain a JSON object.")
    return Policy.from_dict(data)
