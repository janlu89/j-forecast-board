# SPDX-License-Identifier: Apache-2.0
"""Asking the assistant: check the rules first, then stream one answer.

The checks run before anything is sent: an assistant must be set up, and the user's private data
never goes to an external assistant unless the admin policy and a second confirmation allow it.
Every call to an external assistant is written to the audit log (never the question or the data).
"""

from __future__ import annotations

import logging
import secrets
import threading
import time
from dataclasses import dataclass

from ...domain.errors import DomainError, InvalidRequest, NotFound, PolicyViolation
from .configuration import AssistantSetup
from .ports import AgentConfig, AgentRequest, ChatAgent, Emit
from .prompt import SYSTEM, build_prompt
from .tools import Toolbox, ToolError, ToolPermissions, ToolResult

log = logging.getLogger("j_forecast_board")
MAX_QUESTION = 2000
PRIVATE_PAGE = (
    "This page shows your private dataset '{name}'. It is not sent to {destination}. "
    "To ask about it, switch to an assistant that runs on this PC (Local model)."
)


@dataclass(frozen=True)
class PreparedQuestion:
    agent: ChatAgent
    config: AgentConfig
    agent_id: str
    egress: str
    destination: str
    permissions: ToolPermissions
    system: str
    prompt: str
    dataset_key: str | None
    visibility: str | None
    context_level: str


class ToolGateway:
    """Lets an agent running in another process (a CLI) call the tools of one open answer."""

    def __init__(self):
        self._sessions: dict[str, ToolRun] = {}
        self._lock = threading.Lock()

    def open(self, session: ToolRun) -> str:
        token = secrets.token_urlsafe(32)
        with self._lock:
            self._sessions[token] = session
        return token

    def close(self, token: str) -> None:
        with self._lock:
            self._sessions.pop(token, None)

    def is_open(self, token: str) -> bool:
        with self._lock:
            return bool(token) and token in self._sessions

    def call(self, token: str, name: str, arguments: dict) -> ToolResult:
        with self._lock:
            session = self._sessions.get(token)
        if session is None:
            raise NotFound("No open answer for this token.")
        return session.call(name, arguments)


class ToolRun:
    """The tools of one answer: permissions fixed, charts forwarded to the user, uses counted."""

    def __init__(
        self,
        toolbox: Toolbox,
        permissions: ToolPermissions,
        emit: Emit,
        gateway: ToolGateway,
        url: str,
    ):
        self._toolbox = toolbox
        self._permissions = permissions
        self._emit = emit
        self._gateway = gateway
        self._url = url
        self._tokens: list[str] = []
        self.used: list[str] = []
        self.specs = toolbox.specs

    def call(self, name: str, arguments: dict) -> ToolResult:
        self.used.append(name)
        result = self._toolbox.call(name, arguments, self._permissions)
        if result.chart:
            self._emit("chart", chart=result.chart)
        return result

    def remote(self) -> tuple[str, str]:
        token = self._gateway.open(self)
        self._tokens.append(token)
        return self._url, token

    def close(self) -> None:
        for token in self._tokens:
            self._gateway.close(token)


class AskAssistant:
    def __init__(
        self,
        setup: AssistantSetup,
        toolbox: Toolbox,
        gateway: ToolGateway,
        catalog,
        audit,
        timeout: int,
    ):
        self._setup = setup
        self._toolbox = toolbox
        self._gateway = gateway
        self._catalog = catalog
        self._audit = audit
        self._timeout = timeout
        self._one_at_a_time = threading.Lock()

    def prepare(self, question: str, history: list[dict], page: dict) -> PreparedQuestion:
        """Raises InvalidRequest, NotConfigured or PolicyViolation; nothing has been sent yet."""
        question = (question or "").strip()
        if not question:
            raise InvalidRequest("Empty question.")
        if len(question) > MAX_QUESTION:
            raise InvalidRequest("Question too long (max 2,000 characters).")
        agent, config, egress, destination, consent = self._setup.active()
        external = egress == "external"
        private_ok = (
            bool(consent.get("private_data"))
            and self._setup.policy.allow_private_data_to_external_ai
        )
        dataset_key, visibility = self._page_dataset(page)
        if external and visibility == "private" and not private_ok:
            name = page.get("dataset_name") or dataset_key
            self._audit.record(
                "policy_blocked", rule="private_data_to_external_ai", agent=agent.kind.id
            )
            raise PolicyViolation(PRIVATE_PAGE.format(name=name, destination=destination))
        level = self._setup.context_level()
        return PreparedQuestion(
            agent=agent,
            config=config,
            agent_id=agent.kind.id,
            egress=egress,
            destination=destination,
            permissions=ToolPermissions(
                external=external, private_data_allowed=external and private_ok
            ),
            system=SYSTEM,
            prompt=build_prompt(question, history or [], page or {}, level),
            dataset_key=dataset_key,
            visibility=visibility,
            context_level=level,
        )

    def answer(self, prepared: PreparedQuestion, local_url: str, emit: Emit) -> None:
        """Blocking: emits agent, status, text, chart, reset, then done or error."""
        emit(
            "agent",
            id=prepared.agent_id,
            name=prepared.agent.kind.name,
            model=prepared.config.model,
            egress=prepared.egress,
            destination=prepared.destination,
        )
        if self._one_at_a_time.locked():
            emit("status", text="Another question is being answered, waiting for it to finish…")
        with self._one_at_a_time:
            tools = ToolRun(self._toolbox, prepared.permissions, emit, self._gateway, local_url)
            started = time.monotonic()
            outcome = "ok"
            try:
                request = AgentRequest(prepared.system, prepared.prompt, started + self._timeout)
                result = prepared.agent.ask(prepared.config, request, tools, emit)
                emit("done", seconds=result.seconds, turns=result.turns)
            except TimeoutError:
                outcome = "timeout"
                emit("error", text=f"No answer within {self._timeout} s: stopped.")
            except (DomainError, ToolError) as error:
                outcome = "error"
                emit("error", text=str(error))
            except Exception as error:  # the page must always get a final event
                outcome = "error"
                log.exception("Assistant %s failed", prepared.agent_id)
                emit("error", text=f"The assistant failed: {type(error).__name__}.")
            finally:
                tools.close()
                self._record(prepared, tools.used, time.monotonic() - started, outcome)

    def _page_dataset(self, page: dict) -> tuple[str | None, str | None]:
        key = (page or {}).get("dataset")
        if not key:
            return None, None
        try:
            ds = self._catalog.get(key)
        except NotFound:
            return key, None
        return key, ds.visibility.value

    def _record(
        self, prepared: PreparedQuestion, tools: list[str], seconds: float, outcome: str
    ) -> None:
        self._audit.record(
            "assistant_call",
            agent=prepared.agent_id,
            destination=prepared.destination,
            egress=prepared.egress,
            dataset=prepared.dataset_key,
            visibility=prepared.visibility,
            context_level=prepared.context_level,
            bytes_sent=len((prepared.system + prepared.prompt).encode("utf-8")),
            tools=sorted(set(tools)),
            seconds=round(seconds, 1),
            outcome=outcome,
        )
