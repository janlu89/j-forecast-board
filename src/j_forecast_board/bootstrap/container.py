# SPDX-License-Identifier: Apache-2.0
"""Composition root: the only place that knows every adapter and wires them into the use cases."""

from __future__ import annotations

from dataclasses import dataclass

from ..adapters.inbound.http.auth import Authenticator
from ..adapters.outbound.agents.claude_cli import ClaudeCliAgent
from ..adapters.outbound.agents.openai_compatible import API, LOCAL, OpenAICompatibleAgent
from ..adapters.outbound.datasets.catalog import InMemoryCatalog, Loader
from ..adapters.outbound.datasets.csv_upload import CsvTableReader
from ..adapters.outbound.datasets.downloader import Downloader
from ..adapters.outbound.jobs.thread_job_runner import ThreadJobRunner
from ..adapters.outbound.models.stub_model import StubModel
from ..adapters.outbound.models.timestral_model import TimestralModel
from ..adapters.outbound.storage.file_secret_store import FileSecretStore
from ..adapters.outbound.storage.json_settings_store import JsonSettingsStore, load_policy
from ..adapters.outbound.storage.jsonl_audit_log import JsonlAuditLog
from ..adapters.outbound.storage.npz_result_store import NpzResultStore
from ..application.assistant.ask import AskAssistant, ToolGateway
from ..application.assistant.configuration import AssistantSetup
from ..application.assistant.tools import Toolbox
from ..application.credentials import Credentials
from ..application.evaluations import Evaluations
from ..application.forecasts.anomalies import Anomalies
from ..application.forecasts.live import LiveForecast
from ..application.forecasts.replay import Replay
from ..application.forecasts.split import SplitTest
from ..application.forecasts.what_if import WhatIf
from ..application.policy import Policy
from ..application.ports import ForecastModel
from ..application.uploads import Uploads
from ..application.views.overview import Overview
from ..application.views.planner import OrderPlanner
from ..application.views.series import SeriesRanking, SeriesView
from ..application.views.status import EvaluationStatus, StartEvaluation
from ..application.views.total import TotalView
from ..application.workbench import Workbench
from ..domain.forecast import ModelVariant
from .paths import RuntimePaths
from .settings import Settings
from .version import app_version


@dataclass
class Container:
    settings: Settings
    paths: RuntimePaths
    model: ForecastModel
    catalog: InMemoryCatalog
    runner: ThreadJobRunner
    workbench: Workbench
    credentials: Credentials
    authenticator: Authenticator
    uploads: Uploads
    overview: Overview
    series: SeriesView
    ranking: SeriesRanking
    total: TotalView
    status: EvaluationStatus
    start_evaluation: StartEvaluation
    planner: OrderPlanner
    live: LiveForecast
    replay: Replay
    split: SplitTest
    what_if: WhatIf
    anomalies: Anomalies
    policy: Policy
    audit: JsonlAuditLog
    assistant: AssistantSetup
    ask: AskAssistant
    tool_gateway: ToolGateway
    assistant_agents: dict

    def start(self) -> None:
        """Load the built-in datasets, start the worker, queue the background evaluations."""
        self.catalog.load_builtin()
        self.runner.start()
        if not self.settings.background_eval:
            return
        for ds in sorted(self.catalog.list(), key=lambda d: d.N):  # small datasets first
            for i, variant in enumerate(self.workbench.default_variants(ds)):
                priority = 1 if i == 0 else 2
                self.workbench.evaluations.submit(ds, ds.horizon, ds.context, variant, priority)


def build(settings: Settings, loaders: dict[str, Loader] | None = None) -> Container:
    paths = RuntimePaths(settings.home)
    paths.create()
    policy = load_policy(settings.policy_file or paths.config / "policy.json")
    offline = settings.offline or policy.offline  # the admin policy wins
    model: ForecastModel = StubModel() if settings.model == "stub" else TimestralModel(offline)
    catalog = InMemoryCatalog(Downloader(paths.data, offline), loaders)
    runner = ThreadJobRunner()
    evaluations = Evaluations(model, NpzResultStore(paths.results_for(settings.model)), runner)
    workbench = Workbench(catalog, evaluations, model, ModelVariant(settings.default_model_repo))
    secret_store = FileSecretStore(paths.secrets)
    credentials = Credentials(secret_store)
    audit = JsonlAuditLog(paths.logs / "audit.jsonl", app_version())
    views = dict(
        overview=Overview(workbench),
        series=SeriesView(workbench),
        ranking=SeriesRanking(workbench),
        total=TotalView(workbench),
        status=EvaluationStatus(workbench),
        start_evaluation=StartEvaluation(workbench),
        planner=OrderPlanner(workbench),
        live=LiveForecast(workbench),
        replay=Replay(workbench),
        split=SplitTest(workbench),
        what_if=WhatIf(workbench),
        anomalies=Anomalies(workbench),
    )
    agents = {
        LOCAL.id: OpenAICompatibleAgent(LOCAL),
        API.id: OpenAICompatibleAgent(API),
        ClaudeCliAgent.kind.id: ClaudeCliAgent(),
    }
    assistant = AssistantSetup(
        agents,
        JsonSettingsStore(paths.config / "assistant.json"),
        secret_store,
        policy,
        audit,
        app_version(),
    )
    gateway = ToolGateway()
    ask = AskAssistant(
        assistant, Toolbox(workbench, views), gateway, catalog, audit, settings.chat_timeout
    )
    return Container(
        settings=settings,
        paths=paths,
        model=model,
        catalog=catalog,
        runner=runner,
        workbench=workbench,
        credentials=credentials,
        authenticator=Authenticator(credentials, enabled=settings.auth == "on", audit=audit),
        uploads=Uploads(CsvTableReader(), workbench, audit=audit),
        policy=policy,
        audit=audit,
        assistant=assistant,
        ask=ask,
        tool_gateway=gateway,
        assistant_agents=agents,
        **views,
    )
