# Architecture

J-Forecast Board follows *Clean Architecture* (Robert C. Martin): the forecasting rules sit in the
middle and know nothing about the web, the model library, files or the network. The outer layers
plug into them through small interfaces (*ports*).

```
        ┌───────────────────────── bootstrap ─────────────────────────┐
        │  settings · runtime paths · container (wiring) · CLI · doctor │
        │   ┌──────────────────────── adapters ──────────────────────┐ │
        │   │ inbound:  HTTP (FastAPI), stdio MCP server              │ │
        │   │ outbound: Timestral / stub models, datasets, CSV reader,│ │
        │   │           result store, job runner, secrets, settings,  │ │
        │   │           audit log, AI agents (API, Claude CLI)        │ │
        │   │   ┌──────────────────── application ─────────────────┐ │ │
        │   │   │ ports · use cases (views, forecasts, planner,     │ │ │
        │   │   │ uploads, assistant setup and questions) · toolbox │ │ │
        │   │   │   ┌──────────────── domain ────────────────────┐ │ │ │
        │   │   │   │ datasets · model variants · quantiles ·     │ │ │ │
        │   │   │   │ metrics · baselines · calendar · planning   │ │ │ │
        │   │   │   └─────────────────────────────────────────────┘ │ │ │
        │   │   └───────────────────────────────────────────────────┘ │ │
        │   └─────────────────────────────────────────────────────────┘ │
        └───────────────────────────────────────────────────────────────┘
                       dependencies point inward only
```

## The Dependency Rule, enforced

`lint-imports` (configured in `pyproject.toml`) fails the build when:

- a layer imports an outer one (`domain` ← `application` ← `adapters` ← `bootstrap`);
- inbound and outbound adapters import each other;
- `domain` or `application` import FastAPI, pydantic, uvicorn, torch, timestral,
  huggingface_hub or holidays.

numpy and pandas are allowed in the core as the vocabulary of the problem (ADR-0002).

## Where things are

| Package | Holds |
|---|---|
| `domain/` | `series.py` (Dataset, Covariate, Visibility), `forecast.py` (ModelVariant, QuantileForecast, requests), `metrics.py`, `baselines.py`, `calendar.py`, `evaluation.py` (holdout windows), `planning.py` (newsvendor scores), `errors.py` |
| `application/` | `ports.py`; `evaluations.py` (background backtests, scoring panel); `workbench.py` (what every view needs); `views/` (overview, series, total, status, planner); `forecasts/` (live, replay, split, what-if, anomalies); `uploads.py`; `credentials.py`; `policy.py`; `assistant/` (tools, setup, ask, prompt, ports); `view_model.py` |
| `adapters/inbound/http/` | FastAPI app and routes, request bodies, the one error map, sign-in, browser security, static files |
| `adapters/inbound/mcp_stdio/` | the MCP server a CLI assistant starts; forwards tool calls to the app |
| `adapters/outbound/` | `models/` (Timestral, stub), `datasets/` (one module per built-in dataset, downloader, CSV reader, catalog, holidays), `storage/` (npz results, secrets, JSON settings, audit log), `jobs/`, `agents/` (OpenAI-compatible, Claude CLI) |
| `bootstrap/` | `settings.py`, `paths.py`, `container.py` (composition root), `app_factory.py`, `cli.py`, `doctor/` |
| `static/` | the page, `js/` ES modules (core, tabs, chat), CSS, vendored Plotly, manuals |

## How a request flows

`POST /api/overview` → route in `adapters/inbound/http/app.py` validates the body → the `Overview`
use case scores the cached backtests through the `Evaluations` service (which reads them through
the `ResultStore` port) → it returns a *view model* (ADR-0007) → `to_plain` renders numbers and
dates → JSON.

## How to add …

- **a dataset**: one module in `adapters/outbound/datasets/builtin/` with a `load(downloader)`
  function returning a `Dataset`, and one line in `BUILTIN_LOADERS` (`catalog.py`).
- **a forecasting model**: an adapter implementing `ForecastModel` (`application/ports.py`); for a
  model that takes batched arrays, subclass `BatchedQuantileModel` and implement `_load`. Wire it in
  `bootstrap/container.py`.
- **an AI agent**: an adapter implementing `ChatAgent` (`application/assistant/ports.py`) with an
  `AgentKind`, and one line in the `agents` dict of the container. Egress and consent come for free.
- **a tab**: a module in `static/js/tabs/` with `init…`/`run…`/`render…`, the markup in
  `index.html`, and the calls in `static/js/main.js`. If it needs new numbers, add a use case and a
  route; the page only draws (*humble object*).

## Tests

| Folder | What | Needs |
|---|---|---|
| `tests/unit` | domain and application with fakes; front-end module wiring | nothing |
| `tests/integration` | HTTP app on the stub model, assistant end to end with fake providers and a fake CLI, security headers, no-internet run | nothing |
| `tests/golden` | approved JSON of every view, captured from the original demo | fixtures in the repo; `-m model` also needs the Timestral-28M weights |
| `tests/js` | the chat's Markdown renderer (Node's test runner) | Node |
