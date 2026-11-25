# SPDX-License-Identifier: Apache-2.0
"""Errors the application reports to the user. The HTTP layer maps each kind to a status code."""

from __future__ import annotations


class DomainError(Exception):
    """Base class: the message is meant for the user."""


class InvalidRequest(DomainError):
    """The request cannot be served as asked (bad parameters, unsuitable data)."""


class NotFound(DomainError):
    """A dataset, series, model or agent that does not exist."""


class NotReady(DomainError):
    """Something needed is not available yet (e.g. the background evaluation is still running)."""


class NotConfigured(DomainError):
    """A feature needs a setting first (e.g. the AI assistant)."""


class PolicyViolation(DomainError):
    """The data protection rules forbid this (e.g. private data to an external AI)."""


class ModelUnavailable(DomainError):
    """The model weights are missing and cannot be downloaded (offline, network error)."""


class UpstreamError(DomainError):
    """An external service (an AI provider) failed."""
