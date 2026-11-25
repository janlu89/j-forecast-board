"""Tool-calling loop for any OpenAI-compatible Chat Completions API (OpenAI GPT, local llama.cpp / LM Studio / Ollama,
OpenRouter, Mistral, ...). Same tools as the Claude CLI agent (mcp_forecaster.TOOLS), run in-process.

Runs in a worker thread (standard library HTTP only) and reports through emit(kind, **fields):
text | status | chart | error. Streaming is used so the answer appears as it is written.
"""

from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request
from pathlib import Path

from . import mcp_forecaster as M

MAX_TURNS = 10
_THINK = re.compile(r"<think>.*?(</think>|$)", re.S)  # some local models print their reasoning inline


def _tools() -> list[dict]:
    return [dict(type="function", function=dict(name=k, description=d, parameters=s)) for k, (_, d, s) in M.TOOLS.items()]


def _post_stream(cfg: dict, body: dict, deadline: float):
    from .agents import USER_AGENT

    headers = {"Content-Type": "application/json", "Accept": "text/event-stream", "User-Agent": USER_AGENT}
    if cfg.get("api_key"):
        headers["Authorization"] = f"Bearer {cfg['api_key']}"
    req = urllib.request.Request(f"{cfg['base_url'].rstrip('/')}/chat/completions", data=json.dumps(body).encode(), headers=headers)
    timeout = max(5.0, deadline - time.monotonic())
    try:
        resp = urllib.request.urlopen(req, timeout=timeout)
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")[:600]
        try:
            detail = json.loads(detail).get("error", {}).get("message", detail)
        except (ValueError, AttributeError):
            pass
        raise RuntimeError(f"{cfg['name']} API error HTTP {e.code}: {detail}") from None
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise RuntimeError(f"Cannot reach {cfg['base_url']}: {getattr(e, 'reason', e)}. "
                           "If this is the local model, start its server first (it is not started automatically).") from None
    with resp:
        if "text/event-stream" not in resp.headers.get("Content-Type", ""):
            yield json.loads(resp.read())  # server ignored stream=true: one complete response
            return
        for raw in resp:
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


def run(cfg: dict, system: str, prompt: str, run_dir: str, port: int, token: str, timeout: int, emit) -> dict:
    """One answer. Returns {'turns': n, 'seconds': s}."""
    M.URL, M.TOKEN, M.RUN_DIR = f"http://127.0.0.1:{port}", token, run_dir
    M._charts = 0
    seen: set[str] = set()
    t0 = time.monotonic()
    deadline = t0 + timeout
    msgs = [dict(role="system", content=system), dict(role="user", content=prompt)]
    tools = _tools()
    wrote = False
    for turn in range(1, MAX_TURNS + 1):
        emit("status", text="Thinking…" if turn == 1 else "Writing the answer…")
        content, calls, raw_text = "", {}, ""
        body = dict(model=cfg["model"], messages=msgs, tools=tools, tool_choice="auto", stream=True)
        for chunk in _post_stream(cfg, body, deadline):
            for ch in chunk.get("choices") or []:
                d = ch.get("delta") or ch.get("message") or {}
                piece = d.get("content") or ""
                if piece:
                    raw_text += piece
                    visible = _THINK.sub("", raw_text).lstrip() if not content else _THINK.sub("", raw_text)
                    for k in range(len("<think>") - 1, 0, -1):  # hold back a half-received "<think>" tag
                        if visible.endswith("<think>"[:k]):
                            visible = visible[:-k]
                            break
                    if len(visible) > len(content) and visible.startswith(content):
                        if not content and wrote:
                            emit("text", text="\n\n")
                        emit("text", text=visible[len(content):])
                        content = visible
                for tc in d.get("tool_calls") or []:
                    slot = calls.setdefault(tc.get("index", len(calls)), dict(id="", name="", args=""))
                    slot["id"] = tc.get("id") or slot["id"]
                    fn = tc.get("function") or {}
                    slot["name"] += fn.get("name") or ""
                    a = fn.get("arguments")
                    slot["args"] += a if isinstance(a, str) else (json.dumps(a) if a else "")
        wrote = wrote or bool(content)
        if not calls:
            return dict(turns=turn, seconds=round(time.monotonic() - t0, 1))
        calls_list = [calls[i] for i in sorted(calls)]
        for i, c in enumerate(calls_list):
            c["id"] = c["id"] or f"call_{turn}_{i}"
        msgs.append(dict(role="assistant", content=content or None, tool_calls=[
            dict(id=c["id"], type="function", function=dict(name=c["name"], arguments=c["args"] or "{}")) for c in calls_list]))
        for c in calls_list:
            fn = M.TOOLS.get(c["name"], (None,))[0]
            try:
                args = json.loads(c["args"] or "{}")
            except ValueError:
                args = None
            emit("status", text=f"{TOOL_LABELS.get(c['name'], 'Using ' + c['name'])}…", tool=c["name"], input=args)
            if fn is None:
                result = f"Error: unknown tool {c['name']}. Available: {', '.join(M.TOOLS)}"
            elif not isinstance(args, dict):
                result = f"Error: the arguments for {c['name']} were not valid JSON."
            else:
                try:
                    result = fn(args)
                except (M.ToolError, KeyError, ValueError, TypeError) as e:
                    result = f"Error: {e}"
            msgs.append(dict(role="tool", tool_call_id=c["id"], content=result))
            for p in sorted(Path(run_dir).glob("chart_*.json")):
                if p.name not in seen:
                    seen.add(p.name)
                    try:
                        emit("chart", chart=json.loads(p.read_text(encoding="utf-8")))
                    except ValueError:
                        pass
    emit("error", text=f"Stopped after {MAX_TURNS} steps without a final answer.")
    return dict(turns=MAX_TURNS, seconds=round(time.monotonic() - t0, 1))


TOOL_LABELS = {"list_datasets": "Looking at the datasets", "accuracy_summary": "Reading the backtest results",
               "forecast": "Running Timestral", "rank_series": "Ranking the series", "order_plan": "Planning orders",
               "what_if": "Running the scenario", "detect_anomalies": "Scanning for anomalies"}
