"""Chat agents: which AI answers in the 'Ask about this page' panel, and its settings.

Stored in secrets/agents.json under JFB_HOME (permissions 600). API keys are never sent back to the browser:
the API only reports whether a key is set and its last 4 characters.
Kinds:
  claude-cli  Claude Code CLI on this PC (subscription login, no API key)       -> chat.py
  openai      any OpenAI-compatible Chat Completions API with tool calling:
              OpenAI (GPT), a local server (llama.cpp, LM Studio, Ollama, vLLM), OpenRouter, Mistral, ... -> openai_agent.py
"""

from __future__ import annotations

import copy
import json
import os
import shutil
import threading
import urllib.error
import urllib.parse
import urllib.request

from . import paths

CONFIG = paths.current().agent_settings
# Some APIs sit behind Cloudflare, which rejects the default "Python-urllib" User-Agent (Groq: HTTP 403, error 1010).
USER_AGENT = "j-forecast-board/0.1"
_lock = threading.Lock()

CLAUDE_MODELS = ["opus", "sonnet", "haiku", "fable"]
DEFAULTS = {
    "active": "claude",
    "agents": {
        "claude": dict(kind="claude-cli", name="Claude", vendor="Anthropic", model="opus",
                       help="Claude Code CLI on the demo PC: uses its login, no API key."),
        "openai": dict(kind="openai", name="GPT", vendor="OpenAI", base_url="https://api.openai.com/v1", model="", api_key="",
                       help="OpenAI API: needs an API key (platform.openai.com). Pick a model that supports tool calling."),
        "local": dict(kind="openai", name="Local AI", vendor="This PC", base_url="http://127.0.0.1:8090/v1", model="inkling-2-mini-agent",
                      api_key="", help="An OpenAI-compatible server running on this PC (llama.cpp, LM Studio, Ollama, vLLM). "
                                       "Start it yourself; llama.cpp needs --jinja for tool calling. Data never leaves the PC."),
        "custom": dict(kind="openai", name="Other API", vendor="OpenAI-compatible", base_url="", model="", api_key="",
                       help="Any OpenAI-compatible endpoint. Groq: https://api.groq.com/openai/v1 · OpenRouter: https://openrouter.ai/api/v1 · "
                            "Mistral: https://api.mistral.ai/v1. Press Test connection to load the models, then pick one with tool calling."),
    },
}
EDITABLE = {"model", "base_url", "api_key", "name"}


def _load() -> dict:
    cfg = copy.deepcopy(DEFAULTS)
    try:
        saved = json.loads(CONFIG.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return cfg
    if saved.get("active") in cfg["agents"]:
        cfg["active"] = saved["active"]
    for k, a in (saved.get("agents") or {}).items():
        if k in cfg["agents"]:
            cfg["agents"][k].update({f: v for f, v in a.items() if f in EDITABLE and isinstance(v, str)})
    return cfg


def _save(cfg: dict):
    data = dict(active=cfg["active"], agents={k: {f: a.get(f, "") for f in EDITABLE if f in a} for k, a in cfg["agents"].items()})
    tmp = CONFIG.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1)
    os.replace(tmp, CONFIG)
    os.chmod(CONFIG, 0o600)


def get(agent_id: str | None = None) -> dict:
    """Full config of one agent (with its key), for the server side only."""
    with _lock:
        cfg = _load()
    aid = agent_id if agent_id in cfg["agents"] else cfg["active"]
    return dict(id=aid, **cfg["agents"][aid])


def _public(aid: str, a: dict) -> dict:
    key = a.get("api_key") or ""
    out = {k: v for k, v in a.items() if k != "api_key"}
    out.update(id=aid, has_key=bool(key), key_hint=f"…{key[-4:]}" if len(key) >= 8 else ("set" if key else ""))
    if a["kind"] == "claude-cli":
        out["models"] = CLAUDE_MODELS
    out["configured"] = a["kind"] == "claude-cli" or bool(a.get("base_url") and a.get("model"))
    return out


def listing() -> dict:
    with _lock:
        cfg = _load()
    return dict(active=cfg["active"], agents=[_public(k, a) for k, a in cfg["agents"].items()])


def _check_url(url: str) -> str:
    url = (url or "").strip().rstrip("/")
    p = urllib.parse.urlparse(url)
    if p.scheme not in ("http", "https") or not p.netloc:
        raise ValueError("Base URL must start with http:// or https:// (e.g. http://127.0.0.1:8090/v1).")
    return url


def update(agent_id: str, fields: dict, make_active: bool) -> dict:
    with _lock:
        cfg = _load()
        if agent_id not in cfg["agents"]:
            raise ValueError(f"Unknown agent {agent_id}")
        a = cfg["agents"][agent_id]
        for f, v in fields.items():
            if f not in EDITABLE or v is None:
                continue  # None = keep (e.g. an API key left empty in the form)
            v = str(v).strip()
            if f == "base_url" and a["kind"] == "openai":
                v = _check_url(v) if v else ""
            if f == "model" and a["kind"] == "claude-cli" and v not in CLAUDE_MODELS:
                raise ValueError(f"Claude model must be one of {', '.join(CLAUDE_MODELS)}")
            if f in ("model", "name") and len(v) > 120:
                raise ValueError(f"{f} too long")
            if f == "api_key" and len(v) > 400:
                raise ValueError("API key too long")
            if f == "api_key" and a["kind"] != "openai":
                continue
            a[f] = v
        if make_active:
            if a["kind"] == "openai" and not (a.get("base_url") and a.get("model")):
                raise ValueError("Choose a model first: press Test connection, then pick one in the Model field.")
            cfg["active"] = agent_id
        _save(cfg)
    return listing()


def test(agent_id: str, fields: dict | None = None) -> dict:
    """Check that an agent can answer, without starting anything: CLI present / API reachable + its model list.

    fields: unsaved values from the form (an empty api_key means 'use the saved one')."""
    a = get(agent_id)
    if fields:
        a.update({f: str(v).strip() for f, v in fields.items() if f in EDITABLE and v not in (None, "")})
    if a["kind"] == "claude-cli":
        from .chat import CLAUDE

        ok = bool(shutil.which(CLAUDE) or os.path.exists(CLAUDE))
        return dict(ok=ok, message="Claude CLI found on the demo PC." if ok else f"Claude CLI not found ({CLAUDE}).")
    base = _check_url(a.get("base_url", ""))
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    if a.get("api_key"):
        headers["Authorization"] = f"Bearer {a['api_key']}"
    req = urllib.request.Request(f"{base}/models", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=6) as r:
            data = json.loads(r.read())
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")[:300].strip()
        try:
            detail = json.loads(detail).get("error", {}).get("message", detail)
        except (ValueError, AttributeError):
            pass
        hint = " Check the API key." if e.code in (401, 403) else ""
        return dict(ok=False, message=f"{base} answered HTTP {e.code}: {detail or 'no details'}.{hint}")
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        reason = getattr(e, "reason", e)
        local = urllib.parse.urlparse(base).hostname in ("127.0.0.1", "localhost", "::1")
        hint = " Is the local model server running? It is not started automatically." if local else ""
        return dict(ok=False, message=f"Cannot reach {base}: {reason}.{hint}")
    except ValueError:
        return dict(ok=False, message=f"{base}/models did not return JSON: is this an OpenAI-compatible API?")
    models = sorted({m.get("id", "") for m in data.get("data", []) if isinstance(m, dict)} - {""})
    wanted = a.get("model", "")
    msg = f"Connected: {len(models)} model(s) available."
    if wanted and models and wanted not in models and len(models) > 1:
        msg += f" '{wanted}' is not in the list."
    return dict(ok=True, message=msg, models=models[:300])
