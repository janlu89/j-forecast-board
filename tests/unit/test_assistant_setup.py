# SPDX-License-Identifier: Apache-2.0
"""Setting up the assistant: off by default, tested before use, consent before data leaves."""

from __future__ import annotations

import json
import secrets as secrets_module

import pytest
from support.fakes import (
    API_KIND,
    CLI_KIND,
    LOCAL_KIND,
    FakeAgent,
    MemorySecrets,
    MemorySettings,
    RecordingAudit,
)

from j_forecast_board.application.assistant.configuration import AssistantSetup
from j_forecast_board.application.policy import Policy
from j_forecast_board.domain.errors import InvalidRequest, NotConfigured, PolicyViolation

LOCAL_URL = "http://127.0.0.1:8080/v1"
GROQ_URL = "https://api.groq.com/openai/v1"


@pytest.fixture
def audit():
    return RecordingAudit()


@pytest.fixture
def secrets():
    return MemorySecrets()


def make_setup(audit, secrets, policy=None, **agents):
    policy = policy or Policy()
    agents = agents or dict(
        local=FakeAgent(LOCAL_KIND), api=FakeAgent(API_KIND), **{"claude-cli": FakeAgent(CLI_KIND)}
    )
    return AssistantSetup(agents, MemorySettings(), secrets, policy, audit, "0.1.0")


@pytest.fixture
def setup(audit, secrets):
    return make_setup(audit, secrets)


def configure(setup, agent_id="local", url=LOCAL_URL, model="m1", key=None):
    setup.save(agent_id, model, url, key, clear_key=False)
    return setup.test(agent_id)


def test_no_assistant_is_active_on_a_fresh_install(setup):
    listing = setup.listing()
    assert listing["active"] is None
    assert listing["ready"] is False
    assert "No assistant is set up" in listing["reason"]
    with pytest.raises(NotConfigured):
        setup.active()


def test_an_agent_must_be_configured_before_activation(setup):
    with pytest.raises(InvalidRequest, match="not configured"):
        setup.activate("local")


def test_an_agent_must_pass_its_connection_test_before_activation(setup):
    setup.save("local", "m1", LOCAL_URL, None, clear_key=False)
    with pytest.raises(InvalidRequest, match="connection test"):
        setup.activate("local")


def test_a_failed_test_does_not_count(audit, secrets):
    setup = make_setup(audit, secrets, local=FakeAgent(LOCAL_KIND, ok=False))
    assert configure(setup)["ok"] is False
    with pytest.raises(InvalidRequest, match="connection test"):
        setup.activate("local")


def test_a_local_agent_needs_no_consent(setup):
    configure(setup)
    listing = setup.activate("local")
    assert listing["active"] == "local" and listing["ready"]
    local = next(a for a in listing["agents"] if a["id"] == "local")
    assert (local["egress"], local["destination"]) == ("local", "this PC")


def test_changing_the_settings_asks_for_a_new_test(setup):
    configure(setup)
    setup.activate("local")
    setup.save("local", "m2", None, None, clear_key=False)
    assert setup.listing()["ready"] is False
    assert "connection test" in setup.listing()["reason"]


def test_an_external_agent_needs_explicit_consent(setup, audit):
    configure(setup, "api", GROQ_URL, key="k" * 20)
    with pytest.raises(NotConfigured, match="api.groq.com"):
        setup.activate("api")
    listing = setup.activate("api", consent=True)
    assert listing["ready"]
    api = next(a for a in listing["agents"] if a["id"] == "api")
    assert (api["egress"], api["destination"], api["consent"]) == ("external", "api.groq.com", True)
    assert "consent_given" in audit.names()


def test_a_new_destination_asks_for_consent_again(setup):
    configure(setup, "api", GROQ_URL, key="k" * 20)
    setup.activate("api", consent=True)
    configure(setup, "api", "https://openrouter.ai/api/v1", key="k" * 20)
    assert setup.listing()["ready"] is False
    with pytest.raises(NotConfigured, match="openrouter.ai"):
        setup.activate("api")


def test_a_cli_agent_is_external(setup):
    setup.save("claude-cli", "sonnet", None, None, clear_key=False)
    setup.test("claude-cli")
    with pytest.raises(NotConfigured, match="Anthropic"):
        setup.activate("claude-cli")


@pytest.mark.parametrize(
    ("url", "egress"),
    [
        ("http://127.0.0.1:8080/v1", "local"),
        ("http://localhost:11434/v1", "local"),
        ("http://[::1]:1234/v1", "local"),
        ("http://192.168.1.20:8080/v1", "external"),
        ("http://my-gpu-box:8080/v1", "external"),
    ],
)
def test_egress_is_computed_from_where_the_data_goes(setup, url, egress):
    configure(setup, "local", url)
    local = next(a for a in setup.listing()["agents"] if a["id"] == "local")
    assert local["egress"] == egress


def test_the_api_key_is_never_listed(setup, secrets):
    key = secrets_module.token_urlsafe(20)  # generated: no key-like literal in the repository
    configure(setup, "api", GROQ_URL, key=key)
    listing = setup.listing()
    assert key not in json.dumps(listing)
    api = next(a for a in listing["agents"] if a["id"] == "api")
    assert api["has_key"] and api["key_hint"] == f"…{key[-4:]}"
    assert json.loads(secrets.get("agent-keys.json")) == {"api": key}


def test_policy_can_forbid_every_external_assistant(audit, secrets):
    setup = make_setup(audit, secrets, policy=Policy(allow_external_ai=False))
    configure(setup, "api", GROQ_URL, key="k" * 20)
    api = next(a for a in setup.listing()["agents"] if a["id"] == "api")
    assert "disabled by the administrator" in api["blocked"]
    with pytest.raises(PolicyViolation):
        setup.activate("api", consent=True)
    configure(setup)  # a local model is still fine
    assert setup.activate("local")["ready"]


def test_policy_can_list_the_allowed_services(audit, secrets):
    setup = make_setup(audit, secrets, policy=Policy(allowed_ai_hosts=("api.mistral.ai",)))
    configure(setup, "api", GROQ_URL, key="k" * 20)
    with pytest.raises(PolicyViolation, match="not in the list"):
        setup.activate("api", consent=True)
    configure(setup, "api", "https://api.mistral.ai/v1", key="k" * 20)
    assert setup.activate("api", consent=True)["ready"]


def test_private_data_needs_the_policy_and_a_second_confirmation(audit, secrets):
    setup = make_setup(audit, secrets)
    configure(setup, "api", GROQ_URL, key="k" * 20)
    with pytest.raises(PolicyViolation, match="does not allow private data"):
        setup.activate("api", consent=True, private_data=True)
    allowing = make_setup(audit, secrets, policy=Policy(allow_private_data_to_external_ai=True))
    configure(allowing, "api", GROQ_URL, key="k" * 20)
    listing = allowing.activate("api", consent=True, private_data=True)
    assert next(a for a in listing["agents"] if a["id"] == "api")["private_data"]


def test_revoking_consent_switches_the_assistant_off(setup, audit):
    configure(setup, "api", GROQ_URL, key="k" * 20)
    setup.activate("api", consent=True)
    listing = setup.revoke("api")
    assert listing["active"] is None
    assert "consent_revoked" in audit.names()


def test_clearing_an_agent_forgets_its_key(setup, secrets):
    configure(setup, "api", GROQ_URL, key="k" * 20)
    setup.clear("api")
    assert json.loads(secrets.get("agent-keys.json")) == {}


def test_base_url_must_be_http_or_https(setup):
    for bad in ["ftp://host/v1", "127.0.0.1:8080", "http://"]:
        with pytest.raises(InvalidRequest, match="Base URL"):
            setup.save("local", "m1", bad, None, clear_key=False)


def test_cli_models_are_a_fixed_list(setup):
    with pytest.raises(InvalidRequest, match="must be one of"):
        setup.save("claude-cli", "gpt-4", None, None, clear_key=False)


def test_context_level_is_checked(setup):
    assert setup.set_context_level("numbers")["context_level"] == "numbers"
    with pytest.raises(InvalidRequest):
        setup.set_context_level("everything")
