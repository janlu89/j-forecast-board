# SPDX-License-Identifier: Apache-2.0
"""Any OpenAI-compatible Chat Completions API with tool calling (local server, Groq, OpenRouter,
Mistral, OpenAI...). Standard library HTTP only; runs in the worker thread of one answer."""

from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request

from ....application.assistant.ports import (
    AgentConfig,
    AgentKind,
    AgentOutcome,
    AgentRequest,
    CheckResult,
    Emit,
    ToolSession,
)
from ....application.assistant.tools import LABELS, ToolError
from ....domain.errors import DomainError, UpstreamError

# Some APIs sit behind Cloudflare, which rejects Python's default User-Agent (Groq: HTTP 403).
USER_AGENT = "j-forecast-board/0.1"
MAX_TURNS = 10
CHECK_TIMEOUT = 6
_THINK = re.compile(
    r"<think>.*?(</think>|$)", re.S
)  # some local models print their reasoning inline
_THINK_TAG = "<think>"

LOCAL = AgentKind(
    "local",
    "Local model",
    "This PC",
    "An OpenAI-compatible server you run on this PC (llama.cpp, LM Studio, Ollama, vLLM). Start it "
    "yourself; llama.cpp needs --jinja for tool calling. Data never leaves the PC.",
    needs_url=True,
    default_url="http://127.0.0.1:8080/v1",
)
API = AgentKind(
    "api",
    "OpenAI-compatible API",
    "Groq, OpenRouter, Mistral, OpenAI…",
    "An online AI service. Pick a preset or paste its base URL, add your API key, press Test, then "
    "choose a model that supports tool calling. The question and the page you look at are sent "
    "there.",
    needs_url=True,
    needs_key=True,
)


class OpenAICompatibleAgent:
    def __init__(self, kind: AgentKind):
        self.kind = kind

    def check(self, config: AgentConfig) -> CheckResult:
        base = config.base_url.rstrip("/")
        request = urllib.request.Request(
            f"{base}/models", headers=_headers(config, "application/json")
        )
        try:
            with urllib.request.urlopen(request, timeout=CHECK_TIMEOUT) as response:
                data = json.loads(response.read())
        except urllib.error.HTTPError as error:
            hint = " Check the API key." if error.code in (401, 403) else ""
            return CheckResult(False, f"{base} answered HTTP {error.code}: {_detail(error)}.{hint}")
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            return CheckResult(
                False, f"Cannot reach {base}: {getattr(error, 'reason', error)}.{_local_hint(base)}"
            )
        except ValueError:
            return CheckResult(
                False, f"{base}/models did not return JSON: is this an OpenAI-compatible API?"
            )
        models = sorted(
            {m.get("id", "") for m in data.get("data", []) if isinstance(m, dict)} - {""}
        )
        message = f"Connected: {len(models)} model(s) available."
        if config.model and models and config.model not in models and len(models) > 1:
            message += f" '{config.model}' is not in the list."
        return CheckResult(True, message, models)

    def ask(
        self, config: AgentConfig, request: AgentRequest, tools: ToolSession, emit: Emit
    ) -> AgentOutcome:
        started = time.monotonic()
        messages = [
            dict(role="system", content=request.system),
            dict(role="user", content=request.prompt),
        ]
        schemas = [
            dict(
                type="function",
                function=dict(name=t.name, description=t.description, parameters=t.schema),
            )
            for t in tools.specs
        ]
        wrote = False
        for turn in range(1, MAX_TURNS + 1):
            emit("status", text="Thinking…" if turn == 1 else "Writing the answer…")
            body = dict(
                model=config.model,
                messages=messages,
                tools=schemas,
                tool_choice="auto",
                stream=True,
            )
            content, calls = self._one_turn(config, body, request.deadline, emit, wrote)
            wrote = wrote or bool(content)
            if not calls:
                return AgentOutcome(turns=turn, seconds=round(time.monotonic() - started, 1))
            messages.append(
                dict(
                    role="assistant",
                    content=content or None,
                    tool_calls=[
                        dict(
                            id=c["id"],
                            type="function",
                            function=dict(name=c["name"], arguments=c["args"] or "{}"),
                        )
                        for c in calls
                    ],
                )
            )
            for call in calls:
                messages.append(
                    dict(role="tool", tool_call_id=call["id"], content=_run_tool(tools, call, emit))
                )
        raise UpstreamError(f"Stopped after {MAX_TURNS} steps without a final answer.")

    def _one_turn(self, config, body, deadline, emit, wrote) -> tuple[str, list[dict]]:
        content, raw, calls = "", "", {}
        for chunk in _stream(config, body, deadline):
            for choice in chunk.get("choices") or []:
                delta = choice.get("delta") or choice.get("message") or {}
                piece = delta.get("content") or ""
                if piece:
                    raw += piece
                    visible = _visible(raw, content)
                    if len(visible) > len(content) and visible.startswith(content):
                        if not content and wrote:
                            emit("text", text="\n\n")
                        emit("text", text=visible[len(content) :])
                        content = visible
                for tool_call in delta.get("tool_calls") or []:
                    slot = calls.setdefault(
                        tool_call.get("index", len(calls)), dict(id="", name="", args="")
                    )
                    slot["id"] = tool_call.get("id") or slot["id"]
                    function = tool_call.get("function") or {}
                    slot["name"] += function.get("name") or ""
                    arguments = function.get("arguments")
                    slot["args"] += (
                        arguments
                        if isinstance(arguments, str)
                        else (json.dumps(arguments) if arguments else "")
                    )
        ordered = [calls[i] for i in sorted(calls)]
        for i, call in enumerate(ordered):
            call["id"] = call["id"] or f"call_{i}"
        return content, ordered


def _run_tool(tools: ToolSession, call: dict, emit: Emit) -> str:
    try:
        arguments = json.loads(call["args"] or "{}")
    except ValueError:
        arguments = None
    emit(
        "status",
        text=f"{LABELS.get(call['name'], 'Using ' + call['name'])}…",
        tool=call["name"],
        input=arguments,
    )
    if not isinstance(arguments, dict):
        return f"Error: the arguments for {call['name']} were not valid JSON."
    try:
        return tools.call(call["name"], arguments).text
    except (ToolError, DomainError) as error:
        return f"Error: {error}"


def _visible(raw: str, shown: str) -> str:
    """The answer without inline reasoning, holding back a half-received "<think>" tag."""
    visible = _THINK.sub("", raw).lstrip() if not shown else _THINK.sub("", raw)
    for k in range(len(_THINK_TAG) - 1, 0, -1):
        if visible.endswith(_THINK_TAG[:k]):
            return visible[:-k]
    return visible


def _stream(config: AgentConfig, body: dict, deadline: float):
    url = f"{config.base_url.rstrip('/')}/chat/completions"
    headers = _headers(config, "text/event-stream")
    headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=json.dumps(body).encode(), headers=headers)
    timeout = max(5.0, deadline - time.monotonic())
    try:
        response = urllib.request.urlopen(request, timeout=timeout)
    except urllib.error.HTTPError as error:
        raise UpstreamError(
            f"{config.kind.name} API error HTTP {error.code}: {_detail(error)}"
        ) from None
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        reason = getattr(error, "reason", error)
        raise UpstreamError(
            f"Cannot reach {config.base_url}: {reason}.{_local_hint(config.base_url)}"
        ) from None
    with response:
        if "text/event-stream" not in response.headers.get("Content-Type", ""):
            yield json.loads(response.read())  # the server ignored stream=true: one complete answer
            return
        for raw in response:
            if time.monotonic() > deadline:
                raise TimeoutError
            line = raw.decode("utf-8", errors="replace").strip()
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                return
            try:
                yield json.loads(data)
            except ValueError:
                continue


def _headers(config: AgentConfig, accept: str) -> dict:
    headers = {"User-Agent": USER_AGENT, "Accept": accept}
    if config.api_key:
        headers["Authorization"] = f"Bearer {config.api_key}"
    return headers


def _detail(error: urllib.error.HTTPError) -> str:
    detail = error.read().decode(errors="replace")[:600].strip()
    try:
        message = json.loads(detail).get("error", {})
        return (message.get("message") if isinstance(message, dict) else str(message)) or detail
    except (ValueError, AttributeError):
        return detail or "no details"


def _local_hint(base_url: str) -> str:
    host = urllib.parse.urlparse(base_url).hostname
    if host in ("127.0.0.1", "localhost", "::1"):
        return " Is the local model server running? It is not started automatically."
    return ""
