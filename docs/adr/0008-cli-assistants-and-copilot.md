# ADR-0008: CLI assistants, and why Copilot is not shipped yet

Status: Accepted (2026-11-25)

## Context

Assistants that run as CLIs (Claude Code, GitHub Copilot CLI) bring their own tools (shell, files). The app must expose only its forecasting tools. The owner has no Copilot credentials to test with.

## Decision

A CLI assistant runs as a blocking subprocess (same on Windows and Linux) with built-in tools disabled, only our MCP server allowed, no user settings, in an empty temporary folder; prompt on stdin, system prompt in a file. The MCP server forwards calls to the app's `/internal/tools`, which answers only direct calls from this PC and only with the token of an open answer. The Claude Code CLI is shipped. The Copilot CLI is listed as planned: it ships after a spike on a PC with a licence proves the same lock-down (no shell, no file access).

## Consequences

Charts from CLI tool calls reach the page directly. Copilot users see clear instructions in the README in the meantime.
