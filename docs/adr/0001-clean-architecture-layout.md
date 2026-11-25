# ADR-0001: Clean Architecture layout

Status: Accepted (2026-11-25)

## Context

The demo kept everything in a few large modules with global state; it was hard to test without the model and impossible to extend without touching everything.

## Decision

Four layers (domain, application, adapters, bootstrap) with dependencies pointing inward, enforced by import-linter contracts in CI. Use cases receive ports through their constructor. The composition root (`bootstrap/container.py`) is the only place that knows every adapter. The CLI and the doctor live in `bootstrap`, because they start the whole app.

## Consequences

Swapping a model, a dataset source or an AI agent is a new adapter plus one line of wiring. The core is tested without FastAPI, torch or the network. More files than before; `docs/architecture.md` is the map.
