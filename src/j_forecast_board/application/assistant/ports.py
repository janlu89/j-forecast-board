# SPDX-License-Identifier: Apache-2.0
"""What the assistant needs from the outside: AI agents, a settings file, the admin policy."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol

from .tools import ToolResult, ToolSpec

Emit = Callable[..., None]  # emit(kind, **fields): status | text | chart | reset


@dataclass(frozen=True)
class AgentKind:
    """A kind of assistant the user can choose."""

    id: str
    name: str
    vendor: str
    help: str
    needs_url: bool = False  # an OpenAI-compatible endpoint
    needs_key: bool = False
    needs_cli: str | None = None  # an executable on PATH
    default_url: str = ""
    models: tuple[str, ...] = ()  # fixed choices (CLI agents); APIs list theirs


@dataclass(frozen=True)
class AgentConfig:
    kind: AgentKind
    model: str = ""
    base_url: str = ""
    api_key: str = ""


@dataclass(frozen=True)
class CheckResult:
    ok: bool
    message: str
    models: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class AgentRequest:
    system: str
    prompt: str
    deadline: float  # time.monotonic() value


@dataclass(frozen=True)
class AgentOutcome:
    turns: int
    seconds: float


class ToolSession(Protocol):
    """The tools one answer may use, within its permissions."""

    specs: list[ToolSpec]

    def call(self, name: str, arguments: dict) -> ToolResult: ...

    def remote(self) -> tuple[str, str]:
        """(base URL, token) for an agent that calls the tools from another process."""
        ...


class ChatAgent(Protocol):
    kind: AgentKind

    def check(self, config: AgentConfig) -> CheckResult:
        """Can this agent answer (CLI present, API reachable)? Starts nothing; lists models."""
        ...

    def ask(
        self, config: AgentConfig, request: AgentRequest, tools: ToolSession, emit: Emit
    ) -> AgentOutcome:
        """One answer, streamed through emit. Blocking: runs in a worker thread.

        Raises UpstreamError when the provider fails, TimeoutError past the deadline."""
        ...


class SettingsStore(Protocol):
    """A small JSON document with no secrets in it."""

    def load(self) -> dict: ...

    def save(self, data: dict) -> None: ...
