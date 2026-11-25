# SPDX-License-Identifier: Apache-2.0
"""Asking: private data never goes to an external assistant; what is sent follows the settings."""

from __future__ import annotations

import json

import numpy as np
import pytest
from support.fakes import (
    API_KIND,
    LOCAL_KIND,
    FakeAgent,
    MemorySecrets,
    MemorySettings,
    RecordingAudit,
)

from j_forecast_board.application.assistant.ask import AskAssistant, ToolGateway
from j_forecast_board.application.assistant.configuration import AssistantSetup
from j_forecast_board.application.assistant.tools import ToolPermissions
from j_forecast_board.application.policy import Policy
from j_forecast_board.domain.errors import NotConfigured, PolicyViolation
from j_forecast_board.domain.series import Visibility

GROQ_URL = "https://api.groq.com/openai/v1"
PRIVATE_PAGE = {
    "tab": "Overview",
    "dataset": "mine",
    "dataset_name": "My sales",
    "page_text": "WAPE 12%",
}


class FakeCatalog:
    def __init__(self, *datasets):
        self._datasets = {ds.key: ds for ds in datasets}

    def get(self, key):
        from j_forecast_board.domain.errors import NotFound

        if key not in self._datasets:
            raise NotFound(key)
        return self._datasets[key]

    def list(self):
        return list(self._datasets.values())


class FakeToolbox:
    specs: list = []

    def __init__(self):
        self.calls = []

    def call(self, name, arguments, permissions):
        from j_forecast_board.application.assistant.tools import ToolResult

        self.calls.append((name, arguments, permissions))
        return ToolResult("tool text", chart={"kind": "leaderboard", "title": "t", "data": {}})


@pytest.fixture
def datasets(make_dataset):
    public = make_dataset(np.arange(30.0))
    public.key, public.name = "public", "Public data"
    private = make_dataset(np.arange(30.0), visibility=Visibility.PRIVATE)
    private.key, private.name = "mine", "My sales"
    return FakeCatalog(public, private)


def make(datasets, agent, policy=None, private_consent=False, level="full"):
    policy = policy or Policy()
    audit = RecordingAudit()
    setup = AssistantSetup(
        {agent.kind.id: agent}, MemorySettings(), MemorySecrets(), policy, audit, "0.1"
    )
    url = "http://127.0.0.1:8080/v1" if agent.kind is LOCAL_KIND else GROQ_URL
    setup.save(
        agent.kind.id, "m1", url, "k" * 20 if agent.kind.needs_key else None, clear_key=False
    )
    setup.test(agent.kind.id)
    setup.activate(agent.kind.id, consent=True, private_data=private_consent)
    setup.set_context_level(level)
    toolbox = FakeToolbox()
    ask = AskAssistant(setup, toolbox, ToolGateway(), datasets, audit, timeout=30)
    return ask, audit, toolbox


def collect():
    events = []
    return events, lambda kind, **fields: events.append((kind, fields))


def test_nothing_is_asked_before_an_assistant_is_set_up(datasets):
    setup = AssistantSetup({}, MemorySettings(), MemorySecrets(), Policy(), RecordingAudit(), "0.1")
    ask = AskAssistant(setup, FakeToolbox(), ToolGateway(), datasets, RecordingAudit(), timeout=30)
    with pytest.raises(NotConfigured):
        ask.prepare("Is this good?", [], {})


def test_a_private_page_is_not_sent_to_an_external_assistant(datasets):
    ask, audit, _ = make(datasets, FakeAgent(API_KIND))
    with pytest.raises(PolicyViolation, match="private dataset 'My sales'.*api.groq.com"):
        ask.prepare("Explain this", [], PRIVATE_PAGE)
    assert (
        "policy_blocked",
        {"rule": "private_data_to_external_ai", "agent": "api"},
    ) in audit.events


def test_a_private_page_is_fine_with_a_local_assistant(datasets):
    ask, _, _ = make(datasets, FakeAgent(LOCAL_KIND))
    prepared = ask.prepare("Explain this", [], PRIVATE_PAGE)
    assert "WAPE 12%" in prepared.prompt
    assert prepared.permissions == ToolPermissions(external=False, private_data_allowed=False)


def test_policy_and_second_confirmation_allow_private_data(datasets):
    policy = Policy(allow_private_data_to_external_ai=True)
    ask, _, _ = make(datasets, FakeAgent(API_KIND), policy=policy, private_consent=True)
    prepared = ask.prepare("Explain this", [], PRIVATE_PAGE)
    assert prepared.permissions.private_data_allowed


def test_the_policy_alone_does_not_allow_private_data(datasets):
    ask, _, _ = make(
        datasets, FakeAgent(API_KIND), policy=Policy(allow_private_data_to_external_ai=True)
    )
    with pytest.raises(PolicyViolation):
        ask.prepare("Explain this", [], PRIVATE_PAGE)


PAGE = {
    "tab": "Overview",
    "dataset": "public",
    "page_text": "MAPE 5%",
    "page_data": '{"y": [1, 2]}',
}


@pytest.mark.parametrize(
    ("level", "text", "data"),
    [("full", True, True), ("numbers", True, False), ("none", False, False)],
)
def test_the_context_level_decides_what_of_the_page_is_sent(datasets, level, text, data):
    ask, _, _ = make(datasets, FakeAgent(API_KIND), level=level)
    prompt = ask.prepare("Why?", [], PAGE).prompt
    assert ("MAPE 5%" in prompt) is text
    assert ('{"y": [1, 2]}' in prompt) is data
    assert prompt.endswith("User question: Why?")


def test_an_answer_streams_events_and_forwards_charts(datasets):
    agent = FakeAgent(API_KIND, tool=("accuracy_summary", {"dataset": "public"}))
    ask, audit, toolbox = make(datasets, agent)
    events, emit = collect()
    ask.answer(ask.prepare("How good?", [], PAGE), "http://127.0.0.1:1", emit)
    kinds = [kind for kind, _ in events]
    assert kinds[0] == "agent" and kinds[-1] == "done"
    assert "chart" in kinds and ("text", {"text": "An answer."}) in events
    assert events[0][1]["egress"] == "external" and events[0][1]["destination"] == "api.groq.com"
    assert toolbox.calls[0][2] == ToolPermissions(external=True, private_data_allowed=False)


def test_every_call_is_audited_without_the_question_or_the_page(datasets):
    ask, audit, _ = make(datasets, FakeAgent(API_KIND))
    _, emit = collect()
    ask.answer(ask.prepare("a secret question", [], PAGE), "http://127.0.0.1:1", emit)
    name, fields = audit.events[-1]
    assert name == "assistant_call"
    assert fields["destination"] == "api.groq.com" and fields["dataset"] == "public"
    assert (
        fields["visibility"] == "public" and fields["outcome"] == "ok" and fields["bytes_sent"] > 0
    )
    assert "secret question" not in json.dumps(audit.events)
    assert "MAPE 5%" not in json.dumps(audit.events)


def test_a_failing_provider_ends_with_an_error_event(datasets):
    from j_forecast_board.domain.errors import UpstreamError

    agent = FakeAgent(API_KIND)

    def broken(*args, **kwargs):
        raise UpstreamError("Groq API error HTTP 503")

    agent.ask = broken
    ask, audit, _ = make(datasets, agent)
    events, emit = collect()
    ask.answer(ask.prepare("Hi", [], {}), "http://127.0.0.1:1", emit)
    assert events[-1] == ("error", {"text": "Groq API error HTTP 503"})
    assert audit.events[-1][1]["outcome"] == "error"


@pytest.mark.parametrize("question", ["", "   ", "x" * 2001])
def test_empty_or_long_questions_are_refused(datasets, question):
    from j_forecast_board.domain.errors import InvalidRequest

    ask, _, _ = make(datasets, FakeAgent(LOCAL_KIND))
    with pytest.raises(InvalidRequest):
        ask.prepare(question, [], {})
