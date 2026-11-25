# SPDX-License-Identifier: Apache-2.0
"""Setting up the assistant: no agent by default, a passed connection test, consent for egress.

An agent can be activated only when it is configured and its connection test passed with the
saved values. An agent that sends data outside this PC (any vendor CLI, any API not on loopback)
also needs the user's explicit consent for that destination; changing the destination asks again.
"""

from __future__ import annotations

import ipaddress
import json
import threading
import urllib.parse
from dataclasses import dataclass
from datetime import UTC, datetime

from ...domain.errors import InvalidRequest, NotConfigured, NotFound, PolicyViolation
from ..policy import Policy
from .ports import AgentConfig, ChatAgent, CheckResult, SettingsStore

AGENT_KEYS = "agent-keys.json"
CONTEXT_LEVELS = ("full", "numbers", "none")
LOOPBACK_NAMES = ("localhost",)
MAX_FIELD = 120
MAX_KEY = 400


@dataclass(frozen=True)
class Readiness:
    ready: bool
    reason: str = ""


class AssistantSetup:
    def __init__(
        self,
        agents: dict[str, ChatAgent],
        settings: SettingsStore,
        secrets,
        policy: Policy,
        audit,
        app_version: str,
    ):
        self._agents = agents
        self._settings = settings
        self._secrets = secrets
        self.policy = policy
        self._audit = audit
        self._version = app_version
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ queries
    def listing(self) -> dict:
        data = self._load()
        keys = self._keys()
        agents = []
        for agent_id, agent in self._agents.items():
            saved = data["agents"].get(agent_id, {})
            config = self._config(agent_id, saved, keys)
            egress, destination = self.egress(config)
            consent = data["consents"].get(agent_id)
            key = keys.get(agent_id, "")
            agents.append(
                dict(
                    id=agent_id,
                    name=agent.kind.name,
                    vendor=agent.kind.vendor,
                    help=agent.kind.help,
                    needs_url=agent.kind.needs_url,
                    needs_key=agent.kind.needs_key,
                    needs_cli=agent.kind.needs_cli,
                    default_url=agent.kind.default_url,
                    models=list(agent.kind.models),
                    model=config.model,
                    base_url=saved.get("base_url", ""),
                    has_key=bool(key),
                    key_hint=f"…{key[-4:]}" if len(key) >= 8 else ("set" if key else ""),
                    configured=self._configured(config),
                    tested=self._tested(saved, config),
                    egress=egress,
                    destination=destination,
                    consent=bool(consent and consent.get("destination") == destination),
                    private_data=bool(consent and consent.get("private_data")),
                    blocked=self._blocked_reason(config, egress, destination),
                )
            )
        status = self.readiness(data)
        return dict(
            active=data["active"],
            ready=status.ready,
            reason=status.reason,
            agents=agents,
            context_level=data["context_level"],
            policy=self.policy.describe(),
        )

    def readiness(self, data: dict | None = None) -> Readiness:
        data = data or self._load()
        agent_id = data["active"]
        if agent_id is None or agent_id not in self._agents:
            return Readiness(False, "No assistant is set up yet: open the setup to choose one.")
        config = self._config(agent_id, data["agents"].get(agent_id, {}), self._keys())
        egress, destination = self.egress(config)
        blocked = self._blocked_reason(config, egress, destination)
        if blocked:
            return Readiness(False, blocked)
        if not self._tested(data["agents"].get(agent_id, {}), config):
            return Readiness(
                False, "The assistant's connection test has not passed with these settings."
            )
        consent = data["consents"].get(agent_id)
        if egress == "external" and not (consent and consent.get("destination") == destination):
            return Readiness(
                False, f"Data would go to {destination}: confirm it in the setup first."
            )
        return Readiness(True)

    def active(self) -> tuple[ChatAgent, AgentConfig, str, str, dict]:
        """The ready agent: (agent, config, egress, destination, consent). Raises NotConfigured."""
        data = self._load()
        status = self.readiness(data)
        if not status.ready:
            raise NotConfigured(status.reason)
        agent_id = data["active"]
        config = self._config(agent_id, data["agents"].get(agent_id, {}), self._keys())
        egress, destination = self.egress(config)
        return (
            self._agents[agent_id],
            config,
            egress,
            destination,
            data["consents"].get(agent_id) or {},
        )

    def context_level(self) -> str:
        return self._load()["context_level"]

    def egress(self, config: AgentConfig) -> tuple[str, str]:
        """("local" | "external", destination shown to the user)."""
        if config.kind.needs_cli:
            return "external", config.kind.vendor
        host = (urllib.parse.urlparse(config.base_url).hostname or "").lower()
        if not host:
            return "external", "not set"
        return ("local", "this PC") if _is_loopback(host) else ("external", host)

    # ------------------------------------------------------------------ commands
    def save(
        self,
        agent_id: str,
        model: str | None,
        base_url: str | None,
        api_key: str | None,
        clear_key: bool,
    ):
        agent = self._agent(agent_id)
        with self._lock:
            data = self._load()
            saved = dict(data["agents"].get(agent_id, {}))
            if model is not None:
                saved["model"] = _field(model, "model")
                if agent.kind.models and saved["model"] and saved["model"] not in agent.kind.models:
                    raise InvalidRequest(
                        f"{agent.kind.name} model must be one of {', '.join(agent.kind.models)}"
                    )
            if base_url is not None and agent.kind.needs_url:
                saved["base_url"] = _check_url(base_url) if base_url.strip() else ""
            data["agents"][agent_id] = saved
            self._settings.save(data)
            if agent.kind.needs_key and (clear_key or api_key):
                self._set_key(agent_id, "" if clear_key else api_key)
        self._audit.record(
            "agent_configured",
            agent=agent_id,
            destination=self.egress(self._config_of(agent_id))[1],
        )
        return self.listing()

    def test(self, agent_id: str, model=None, base_url=None, api_key=None) -> dict:
        """Try the connection; values not given are taken from the saved settings."""
        agent = self._agent(agent_id)
        saved = self._load()["agents"].get(agent_id, {})
        current = self._config_of(agent_id)
        candidate = AgentConfig(
            agent.kind,
            model=(model if model not in (None, "") else current.model).strip(),
            base_url=_check_url(base_url) if base_url else current.base_url,
            api_key=api_key or current.api_key,
        )
        egress, destination = self.egress(candidate)
        blocked = self._blocked_reason(candidate, egress, destination)
        if blocked:
            return dict(ok=False, message=blocked, models=[])
        result: CheckResult = agent.check(candidate)
        if result.ok and _same(candidate, current) and self._configured(current):
            with self._lock:
                data = self._load()
                record = dict(data["agents"].get(agent_id, saved))
                record["tested"] = _fingerprint(current)
                data["agents"][agent_id] = record
                self._settings.save(data)
        return dict(ok=result.ok, message=result.message, models=result.models[:300])

    def activate(self, agent_id: str, consent: bool = False, private_data: bool = False) -> dict:
        agent = self._agent(agent_id)
        config = self._config_of(agent_id)
        if not self._configured(config):
            raise InvalidRequest(
                f"{agent.kind.name} is not configured yet: set its model and address first."
            )
        egress, destination = self.egress(config)
        blocked = self._blocked_reason(config, egress, destination)
        if blocked:
            raise PolicyViolation(blocked)
        saved = self._load()["agents"].get(agent_id, {})
        if not self._tested(saved, config):
            raise InvalidRequest(
                "Run the connection test with these settings first (and make sure it passes)."
            )
        with self._lock:
            data = self._load()
            previous = data["consents"].get(agent_id)
            if egress == "external" and not (
                previous and previous.get("destination") == destination
            ):
                if not consent:
                    raise NotConfigured(
                        f"Data would go to {destination}: the user must confirm it first."
                    )
                data["consents"][agent_id] = dict(
                    destination=destination,
                    accepted_at=datetime.now(UTC).isoformat(timespec="seconds"),
                    app_version=self._version,
                )
                self._audit.record("consent_given", agent=agent_id, destination=destination)
            if egress == "external" and private_data:
                if not self.policy.allow_private_data_to_external_ai:
                    raise PolicyViolation(
                        "The policy on this PC does not allow private data to go to an external AI."
                    )
                data["consents"][agent_id]["private_data"] = True
                self._audit.record(
                    "consent_given", agent=agent_id, destination=destination, private_data=True
                )
            data["active"] = agent_id
            self._settings.save(data)
        self._audit.record(
            "agent_activated", agent=agent_id, destination=destination, egress=egress
        )
        return self.listing()

    def deactivate(self) -> dict:
        with self._lock:
            data = self._load()
            data["active"] = None
            self._settings.save(data)
        return self.listing()

    def revoke(self, agent_id: str) -> dict:
        self._agent(agent_id)
        with self._lock:
            data = self._load()
            if data["consents"].pop(agent_id, None) is not None:
                self._audit.record("consent_revoked", agent=agent_id)
            if data["active"] == agent_id:
                data["active"] = None
            self._settings.save(data)
        return self.listing()

    def set_context_level(self, level: str) -> dict:
        if level not in CONTEXT_LEVELS:
            raise InvalidRequest(f"Context level must be one of {', '.join(CONTEXT_LEVELS)}")
        with self._lock:
            data = self._load()
            data["context_level"] = level
            self._settings.save(data)
        return self.listing()

    def clear(self, agent_id: str) -> dict:
        """Forget an agent's settings and key."""
        self._agent(agent_id)
        with self._lock:
            data = self._load()
            data["agents"].pop(agent_id, None)
            data["consents"].pop(agent_id, None)
            if data["active"] == agent_id:
                data["active"] = None
            self._settings.save(data)
            self._set_key(agent_id, "")
        return self.listing()

    # ------------------------------------------------------------------ internals
    def _agent(self, agent_id: str) -> ChatAgent:
        if agent_id not in self._agents:
            raise NotFound(f"Unknown assistant {agent_id}")
        return self._agents[agent_id]

    def _load(self) -> dict:
        data = self._settings.load() or {}
        active = data.get("active")
        level = data.get("context_level")
        return dict(
            active=active if active in self._agents else None,
            agents={
                k: v
                for k, v in (data.get("agents") or {}).items()
                if k in self._agents and isinstance(v, dict)
            },
            consents={k: v for k, v in (data.get("consents") or {}).items() if isinstance(v, dict)},
            context_level=level if level in CONTEXT_LEVELS else "full",
        )

    def _keys(self) -> dict:
        try:
            return json.loads(self._secrets.get(AGENT_KEYS) or "{}")
        except ValueError:
            return {}

    def _set_key(self, agent_id: str, key: str) -> None:
        key = (key or "").strip()
        if len(key) > MAX_KEY:
            raise InvalidRequest("API key too long")
        keys = self._keys()
        if key:
            keys[agent_id] = key
        else:
            keys.pop(agent_id, None)
        self._secrets.set(AGENT_KEYS, json.dumps(keys))

    def _config(self, agent_id: str, saved: dict, keys: dict) -> AgentConfig:
        agent = self._agents[agent_id]
        model = saved.get("model") or (agent.kind.models[0] if agent.kind.models else "")
        base_url = saved.get("base_url") or ""
        return AgentConfig(
            agent.kind, model=model, base_url=base_url, api_key=keys.get(agent_id, "")
        )

    def _config_of(self, agent_id: str) -> AgentConfig:
        return self._config(agent_id, self._load()["agents"].get(agent_id, {}), self._keys())

    @staticmethod
    def _configured(config: AgentConfig) -> bool:
        if config.kind.needs_url and not (config.base_url and config.model):
            return False
        return bool(config.model)

    @staticmethod
    def _tested(saved: dict, config: AgentConfig) -> bool:
        return saved.get("tested") == _fingerprint(config)

    def _blocked_reason(self, config: AgentConfig, egress: str, destination: str) -> str:
        """Why the admin policy forbids this destination, or '' when it is allowed."""
        if egress == "local":
            return ""
        if not self.policy.allow_external_ai:
            return "External AI services are disabled by the administrator's policy on this PC."
        allowed = self.policy.allowed_ai_hosts
        if (
            allowed is not None
            and destination.lower() not in allowed
            and config.kind.id not in allowed
        ):
            return (
                f"{destination} is not in the list of AI services allowed by the policy on this PC."
            )
        return ""


def _fingerprint(config: AgentConfig) -> str:
    """What the connection test vouches for; any change asks for a new test."""
    import hashlib

    raw = f"{config.kind.id}|{config.model}|{config.base_url}|{config.api_key}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _same(a: AgentConfig, b: AgentConfig) -> bool:
    return (a.model, a.base_url, a.api_key) == (b.model, b.base_url, b.api_key)


def _field(value: str, name: str) -> str:
    value = str(value).strip()
    if len(value) > MAX_FIELD:
        raise InvalidRequest(f"{name} too long")
    return value


def _check_url(url: str) -> str:
    url = (url or "").strip().rstrip("/")
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc or not parsed.hostname:
        raise InvalidRequest(
            "Base URL must start with http:// or https:// (e.g. http://127.0.0.1:8080/v1)."
        )
    return url


def _is_loopback(host: str) -> bool:
    if host in LOOPBACK_NAMES:
        return True
    try:
        return ipaddress.ip_address(host.strip("[]")).is_loopback
    except ValueError:
        return False


LOCAL_CANDIDATES = (
    ("llama.cpp", "http://127.0.0.1:8080/v1"),
    ("llama.cpp (alternative port)", "http://127.0.0.1:8090/v1"),
    ("Ollama", "http://127.0.0.1:11434/v1"),
    ("LM Studio", "http://127.0.0.1:1234/v1"),
)


def detect_local_servers(agent: ChatAgent) -> list[dict]:
    """Probe the usual ports of local model servers on loopback (only when the user asks)."""
    found = []
    for name, url in LOCAL_CANDIDATES:
        result = agent.check(AgentConfig(agent.kind, base_url=url))
        if result.ok:
            found.append(dict(name=name, base_url=url, models=result.models[:50]))
    return found
