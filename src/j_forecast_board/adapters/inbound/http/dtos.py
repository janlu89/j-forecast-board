# SPDX-License-Identifier: Apache-2.0
"""Request bodies of the HTTP API (validated by pydantic; 422 when malformed)."""

from __future__ import annotations

from pydantic import BaseModel


class DatasetRequest(BaseModel):
    dataset: str
    horizon: int | None = None
    context: int | None = None


class SeriesRequest(DatasetRequest):
    series: int = 0
    variant: str | None = None


class RunRequest(DatasetRequest):
    variant: str


class ReplayRequest(SeriesRequest):
    frames: int = 40
    span: int | None = None


class LiveRequest(SeriesRequest):
    origin: str | None = None  # date: forecast as if today were this date (default: end of data)


class SplitRequestBody(SeriesRequest):
    start: str | None = None
    split: str | None = None
    end: str | None = None


class EditBody(BaseModel):
    name: str
    mode: str = "keep"
    value: float = 0
    start: int = 0
    end: int | None = None


class WhatIfBody(SeriesRequest):
    edits: list[EditBody] = []


class AnomalyRequest(SeriesRequest):
    step: int | None = None
    windows: int = 20
    level: float = 0.98


class PlanBody(SeriesRequest):
    scope: str = "all"
    margin: float = 0.4
    holding: float = 0.15
    target: float = 0.95


class RegisterBody(BaseModel):
    uid: str
    date_col: str
    target: str
    id_col: str | None = None
    past: list[str] = []
    known: list[str] = []
    cat: list[str] = []
    freq: str | None = None
    season: int | None = None
    horizon: int | None = None
    calendar: bool = True
    country: str | None = None
    name: str | None = None
    agg: str = "sum"


class ChatBody(BaseModel):
    message: str
    history: list[dict] = []
    context: dict = {}


class AgentBody(BaseModel):
    model: str | None = None
    base_url: str | None = None
    api_key: str | None = None  # None or "" = keep the saved key
    clear_key: bool = False


class ActivateBody(BaseModel):
    id: str
    consent: bool = False  # the user ticked "send my questions and this page to ..."
    private_data: bool = False  # second confirmation, only when the policy allows it


class ContextBody(BaseModel):
    level: str
