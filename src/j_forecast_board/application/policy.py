# SPDX-License-Identifier: Apache-2.0
"""Admin policy: rules an administrator can set for a managed PC (config/policy.json).

A policy rule wins over the user's own settings. Without a policy file the defaults apply.
"""

from __future__ import annotations

from dataclasses import dataclass, fields


@dataclass(frozen=True)
class Policy:
    allow_external_ai: bool = True
    allow_private_data_to_external_ai: bool = False
    allowed_ai_hosts: tuple[str, ...] | None = None  # None = any host; () = no external host
    persist_uploads: bool = False
    offline: bool = False

    @classmethod
    def from_dict(cls, data: dict) -> Policy:
        known = {f.name for f in fields(cls)}
        unknown = sorted(set(data) - known)
        if unknown:
            raise ValueError(f"Unknown policy keys: {', '.join(unknown)}")
        values = dict(data)
        hosts = values.get("allowed_ai_hosts")
        if hosts is not None:
            values["allowed_ai_hosts"] = tuple(str(h).lower() for h in hosts)
        for name in (
            "allow_external_ai",
            "allow_private_data_to_external_ai",
            "persist_uploads",
            "offline",
        ):
            if name in values and not isinstance(values[name], bool):
                raise ValueError(f"Policy key {name} must be true or false.")
        return cls(**values)

    def allows_host(self, host: str) -> bool:
        if not self.allow_external_ai:
            return False
        return self.allowed_ai_hosts is None or host.lower() in self.allowed_ai_hosts

    def describe(self) -> dict:
        return dict(
            allow_external_ai=self.allow_external_ai,
            allow_private_data_to_external_ai=self.allow_private_data_to_external_ai,
            allowed_ai_hosts=list(self.allowed_ai_hosts)
            if self.allowed_ai_hosts is not None
            else None,
            persist_uploads=self.persist_uploads,
            offline=self.offline,
        )
