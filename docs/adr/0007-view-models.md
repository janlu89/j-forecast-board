# ADR-0007: View models instead of presenters per view

Status: Accepted (2026-11-25)

## Context

The roadmap asked use cases to return domain types and presenters to shape JSON. The views' purpose is precisely to assemble many numbers; a typed result class plus a presenter per view would double about 1,500 lines and add a place for mistakes.

## Decision

Use cases return a *view model*: nested dicts and lists of domain values (numpy arrays, floats, dates). Two small wrappers state presentation needs: `Numbers(values, digits)` and `Dates(dataset, steps)`. One generic `to_plain` renders them (rounding, non-finite to null, dates in the dataset's format). Scores that other numbers are derived from are rounded first (`clean`) so derived values match what is shown.

## Consequences

Use cases stay free of FastAPI and pydantic and are tested directly; the HTTP layer only serialises. Key order and numbers are pinned by the golden tests.
