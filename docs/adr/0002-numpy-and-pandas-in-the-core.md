# ADR-0002: numpy and pandas in the core

Status: Accepted (2026-11-25)

## Context

The domain is numeric: panels of time series, masks, quantiles. Wrapping numpy and pandas behind our own types would add code and slow every computation.

## Decision

numpy and pandas are allowed in `domain` and `application`. Nothing else outside the standard library is (contract in `pyproject.toml`).

## Consequences

The core depends on two stable, ubiquitous libraries. Web frameworks, the model library, `holidays` and file formats stay outside.
