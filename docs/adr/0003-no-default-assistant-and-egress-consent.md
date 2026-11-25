# ADR-0003: No default assistant, consent before data leaves

Status: Accepted (2026-11-25)

## Context

The only way data can leave the PC is the AI assistant. The owner's requirement: it must be configured, or it does not start; leaving the PC must be visible and deliberate.

## Decision

No assistant is active on a fresh install. An assistant becomes usable only when it is configured, its connection test passed with the saved values, and, when it sends data outside this PC, the user confirmed that destination (stored with time and app version; a new destination asks again). Egress is computed from where the data goes: loopback is local, any other host and every vendor CLI is external. Uploaded datasets are private: refused for external assistants in the use case and in every tool, unless the admin policy and a second confirmation allow it. Every call is audited without content.

## Consequences

The chat shows a clear Local / External badge. Users who want an online service click once more. Policy can disable external services entirely.
