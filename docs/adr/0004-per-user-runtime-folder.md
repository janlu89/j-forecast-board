# ADR-0004: Per-user runtime folder

Status: Accepted (2026-11-25)

## Context

The demo kept a plain-text password and a live API key inside the program folder: one `git add .` away from a leak.

## Decision

Every runtime file lives in a per-user folder outside the code (`%LOCALAPPDATA%\JForecastBoard`, `~/.local/share/j-forecast-board`, or `JFB_HOME`). Secrets in `secrets/` (0600 on POSIX); settings without secrets in `config/`.

## Consequences

Secrets cannot be committed; `git clean` cannot wipe user data; `purge` deletes everything in one step.
