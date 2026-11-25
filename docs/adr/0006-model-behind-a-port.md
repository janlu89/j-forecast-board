# ADR-0006: The forecasting model behind a port

Status: Accepted (2026-11-25)

## Context

Tests and installation checks must run without the Timestral weights (licence, size, network), and other models should be possible later.

## Decision

`ForecastModel` port. Adapters: Timestral (`TimestralModel`) and a deterministic stub (`StubModel`, `JFB_MODEL=stub`). Both share `BatchedQuantileModel`, the anti-corruption layer that turns dataset items into the model's batched inputs. Stub names carry "· stub" everywhere and its results are cached apart.

## Consequences

Fast tests and a weight-free doctor. A new model is one adapter.
