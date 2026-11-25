# SPDX-License-Identifier: Apache-2.0
"""Small in-memory stand-ins for the assistant's ports."""

from __future__ import annotations

from j_forecast_board.application.assistant.ports import (
    AgentConfig,
    AgentKind,
    AgentOutcome,
    AgentRequest,
    CheckResult,
)

LOCAL_KIND = AgentKind("local", "Local model", "This PC", "help", needs_url=True)
API_KIND = AgentKind("api", "API", "Groq…", "help", needs_url=True, needs_key=True)
CLI_KIND = AgentKind(
    "claude-cli", "Claude Code CLI", "Anthropic", "help", needs_cli="claude", models=("sonnet",)
)


class MemorySettings:
    def __init__(self):
        self.data: dict = {}

    def load(self) -> dict:
        return dict(self.data)

    def save(self, data: dict) -> None:
        self.data = dict(data)


class MemorySecrets:
    def __init__(self):
        self.values: dict[str, str] = {}

    def get(self, name):
        return self.values.get(name)

    def set(self, name, value):
        self.values[name] = value

    def delete(self, name):
        self.values.pop(name, None)


class RecordingAudit:
    def __init__(self):
        self.events: list[tuple[str, dict]] = []

    def record(self, event: str, **fields) -> None:
        self.events.append((event, fields))

    def names(self) -> list[str]:
        return [name for name, _ in self.events]


class FakeAgent:
    """Answers with a fixed text; may call one tool first."""

    def __init__(self, kind: AgentKind, ok: bool = True, tool: tuple[str, dict] | None = None):
        self.kind = kind
        self.ok = ok
        self.tool = tool
        self.requests: list[AgentRequest] = []

    def check(self, config: AgentConfig) -> CheckResult:
        return CheckResult(self.ok, "fine" if self.ok else "unreachable", ["m1", "m2"])

    def ask(self, config, request, tools, emit) -> AgentOutcome:
        self.requests.append(request)
        if self.tool:
            name, arguments = self.tool
            emit("status", text=f"{name}…")
            tools.call(name, arguments)
        emit("text", text="An answer.")
        return AgentOutcome(turns=2 if self.tool else 1, seconds=0.1)
