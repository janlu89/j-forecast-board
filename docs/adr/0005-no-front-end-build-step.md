# ADR-0005: No front-end build step

Status: Accepted (2026-11-25)

## Context

Target PCs may have no Node and no internet beyond pip. A bundler would be the only reason to need Node.

## Decision

Vanilla JavaScript as native ES modules, Plotly vendored. The app's code is served with `Cache-Control: no-cache` so browsers revalidate modules after an update (module imports cannot carry a version).

## Consequences

Setup needs only Python. No minification; the page loads a couple of dozen small modules on loopback, which is fast.
