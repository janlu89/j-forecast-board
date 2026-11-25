"""'Ask about this page': an English chat that explains what the user sees and calls the demo's forecasting tools
(mcp_forecaster.py). The agent is chosen in the chat's settings (agents.py): the Claude Code CLI (default, no API key)
or any OpenAI-compatible API, including a local model server (openai_agent.py).

Safety: the page is reachable from the internet (behind the demo login), so the CLI runs with no built-in
tools at all (--tools ""), only our MCP tools allowed (--permission-mode dontAsk), no user settings/hooks,
in an empty temporary directory, one question at a time, with a time limit.
Streams newline-delimited JSON events to the page: status | text | chart | done | error.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

from . import agents as AG
from . import auth as A
from . import openai_agent as OA

CLAUDE = os.environ.get("TIMESTRAL_CHAT_CLI") or shutil.which("claude") or str(Path.home() / ".local/bin/claude")
MODEL = os.environ.get("TIMESTRAL_CHAT_MODEL", "opus")
TIMEOUT = int(os.environ.get("TIMESTRAL_CHAT_TIMEOUT", "240"))
MCP_SERVER = Path(__file__).with_name("mcp_forecaster.py")
_LOCK = asyncio.Lock()

TOOL_LABELS = {"list_datasets": "Looking at the datasets", "accuracy_summary": "Reading the backtest results",
               "forecast": "Running Timestral", "rank_series": "Ranking the series", "order_plan": "Planning orders",
               "what_if": "Running the scenario", "detect_anomalies": "Scanning for anomalies"}

SYSTEM = """You are the forecasting assistant inside an internal demo of Timestral, Mistral AI's open time-series
foundation model (sizes 5M, 28M, 123M, 209M parameters; zero-shot: no training on the user's data; outputs 21 quantiles;
runs on a normal CPU). The audience is a mixed team (developers, a PM, business people, an AI integration engineer)
evaluating it for retail demand forecasting.

Rules:
- Always answer in English, even if the question is in another language.
- The chat sits next to the app: each question comes with a "Current page" block describing what the user sees right
  now (tab, dataset, series, model, the visible text with its numbers, and the chart data in compact form). Questions
  like "explain this", "why is it like this", "these numbers" refer to that page. Explain what is on screen first, in plain
  words, pointing at the specific numbers; then add what it means for a retailer.
- Every number you state must come from the Current page block or a tool result in this conversation. Never invent or
  estimate figures. If neither can answer, say so.
- When you need more detail than the page shows, call a tool with the page's dataset, series id and model (model names
  look like "Timestral-28M · closed = missing": pass just the size, e.g. "Timestral-28M").
- Be concise and business-friendly: lead with the answer, then 2-5 short bullets. Explain metrics in plain words the
  first time (MAPE/WAPE = average % error; P10-P90 = 80% uncertainty band; bias + = over-forecast).
- Be honest about limits: zero-shot results on one holdout period; what-if shows the model's reaction, not a measured
  causal effect; new products without history and very sparse (intermittent) sales are hard for these models.
- Charts produced by tools are shown to the user automatically under your answer: refer to "the chart below" and do
  not print long tables of numbers.
- The datasets are public (Rossmann drugstores, airline passengers, electricity load, bike sharing, temperatures and
  any CSV the user uploaded). For Rossmann the series ids are store numbers.
- Licensing, if asked: weights are "Modified MIT", free except for companies with consolidated revenue above
  $20M per month (also when the employer is above it); above that a commercial licence from Mistral is needed.
  Fine-tuning is offered through Mistral Forge.
- Use short Markdown (bold, bullet lists, small tables). No headings larger than ###."""


def _ev(kind: str, **kw) -> bytes:
    return (json.dumps(dict(type=kind, **kw)) + "\n").encode()


def _prompt(message: str, history: list[dict], context: dict) -> str:
    parts = []
    if context:
        c = {k: v for k, v in context.items() if v not in (None, "")}
        head = " | ".join(f"{k}: {c[k]}" for k in ("tab", "dataset", "dataset_name", "series_label", "series_id", "model", "horizon",
                                                   "context_length") if k in c)
        block = f"Current page (what the user sees right now in the app; its numbers come from the app's own runs):\n{head}"
        if c.get("page_text"):
            block += f"\n--- visible text ---\n{str(c['page_text'])[:7000]}"
        if c.get("page_data"):
            block += f"\n--- chart data (compact JSON; long series summarised as n/first/last/min/max/mean) ---\n{str(c['page_data'])[:6000]}"
        parts.append(block)
    turns = [h for h in history if h.get("role") in ("user", "assistant") and h.get("text")][-8:]
    if turns:
        parts.append("Conversation so far:\n" + "\n".join(f"{'User' if h['role'] == 'user' else 'Assistant'}: {h['text'][:1500]}"
                                                         for h in turns))
    parts.append(f"User question: {message}")
    return "\n\n".join(parts)


async def stream(message: str, history: list[dict], context: dict, port: int):
    message = (message or "").strip()
    if not message:
        yield _ev("error", text="Empty question.")
        return
    if len(message) > 2000:
        yield _ev("error", text="Question too long (max 2,000 characters).")
        return
    agent = AG.get()
    yield _ev("agent", id=agent["id"], name=agent["name"], model=agent.get("model", ""))
    if agent["kind"] == "claude-cli" and not Path(CLAUDE).exists():
        yield _ev("error", text="The Claude CLI was not found on the demo PC.")
        return
    if agent["kind"] == "openai" and not (agent.get("base_url") and agent.get("model")):
        yield _ev("error", text=f"{agent['name']} is not configured: open the agent settings (⚙) and set the base URL and model.")
        return
    if _LOCK.locked():
        yield _ev("status", text="Another question is being answered, waiting for it to finish…")
    async with _LOCK:
        if agent["kind"] == "openai":
            async for chunk in _run_openai(agent, message, history, context, port):
                yield chunk
            return
        for attempt in (1, 2):
            state = {"failed": False}
            async for chunk in _run(message, history, context, port, state, last=attempt == 2, model=agent.get("model") or MODEL):
                yield chunk
            if not state["failed"]:
                break
            yield _ev("reset", text="The assistant stopped unexpectedly, retrying once…")


async def _run_openai(agent: dict, message: str, history: list[dict], context: dict, port: int):
    """OpenAI-compatible agent: the blocking HTTP loop runs in a thread and hands events over through a queue."""
    loop = asyncio.get_running_loop()
    q: asyncio.Queue = asyncio.Queue()
    run_dir = tempfile.mkdtemp(prefix="timestral-chat-")
    os.chmod(run_dir, 0o700)

    def emit(kind, **kw):
        loop.call_soon_threadsafe(q.put_nowait, _ev(kind, **kw))

    def work():
        try:
            res = OA.run(agent, SYSTEM, _prompt(message, history, context), run_dir, port, A.INTERNAL_TOKEN, TIMEOUT, emit)
            emit("done", seconds=res["seconds"], turns=res["turns"])
        except TimeoutError:
            emit("error", text=f"No answer within {TIMEOUT} s: stopped.")
        except Exception as e:  # report any failure to the page instead of a broken stream
            print(f"[chat] {agent['id']} failed: {type(e).__name__}: {e}", flush=True)
            emit("error", text=str(e) or type(e).__name__)
        finally:
            loop.call_soon_threadsafe(q.put_nowait, None)

    task = loop.run_in_executor(None, work)
    try:
        while (item := await q.get()) is not None:
            yield item
    finally:
        await task
        shutil.rmtree(run_dir, ignore_errors=True)


async def _run(message: str, history: list[dict], context: dict, port: int, state: dict, last: bool = True, model: str = MODEL):
    """One CLI run. On failure sets state['failed']; the error is only shown to the user on the last attempt."""
    run_dir = tempfile.mkdtemp(prefix="timestral-chat-")
    os.chmod(run_dir, 0o700)
    cfg = os.path.join(run_dir, "mcp.json")
    with open(os.open(cfg, os.O_WRONLY | os.O_CREAT, 0o600), "w", encoding="utf-8") as f:
        json.dump({"mcpServers": {"forecaster": {"type": "stdio", "command": sys.executable, "args": [str(MCP_SERVER)],
                                                 "env": {"FORECASTER_URL": f"http://127.0.0.1:{port}", "FORECASTER_TOKEN": A.INTERNAL_TOKEN,
                                                         "FORECASTER_RUN_DIR": run_dir}}}}, f)
    cmd = [CLAUDE, "-p", "--output-format", "stream-json", "--verbose", "--include-partial-messages",
           "--model", model, "--tools", "", "--strict-mcp-config", "--mcp-config", cfg,
           "--allowedTools", "mcp__forecaster", "--permission-mode", "dontAsk", "--setting-sources", "project",
           "--disable-slash-commands", "--no-session-persistence", "--max-turns", "12", "--system-prompt", SYSTEM]
    seen: set[str] = set()
    streamed = False
    proc = None
    try:
        yield _ev("status", text="Thinking…")
        proc = await asyncio.create_subprocess_exec(*cmd, cwd=run_dir, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                                                    stderr=asyncio.subprocess.PIPE, limit=16 * 1024 * 1024)
        proc.stdin.write(_prompt(message, history, context).encode())
        await proc.stdin.drain()
        proc.stdin.close()
        loop = asyncio.get_running_loop()
        deadline = loop.time() + TIMEOUT
        while True:
            left = deadline - loop.time()
            if left <= 0:
                yield _ev("error", text=f"No answer within {TIMEOUT} s: stopped.")
                break
            try:
                line = await asyncio.wait_for(proc.stdout.readline(), timeout=left)
            except asyncio.TimeoutError:
                continue
            if not line:
                break
            try:
                ev = json.loads(line)
            except ValueError:
                continue
            t = ev.get("type")
            if t == "stream_event":
                e = ev.get("event", {})
                d = e.get("delta", {})
                if e.get("type") == "content_block_delta" and d.get("type") == "text_delta":
                    streamed = True
                    yield _ev("text", text=d.get("text", ""))
                elif e.get("type") == "message_start" and streamed:
                    yield _ev("text", text="\n\n")  # a new assistant turn after tool calls
            elif t == "assistant":
                for b in ev.get("message", {}).get("content", []):
                    if b.get("type") == "tool_use":
                        name = b.get("name", "").split("__")[-1]
                        yield _ev("status", text=TOOL_LABELS.get(name, f"Using {name}") + "…", tool=name, input=b.get("input"))
            elif t == "user":  # tool results arrived: forward any new chart
                for p in sorted(Path(run_dir).glob("chart_*.json")):
                    if p.name not in seen:
                        seen.add(p.name)
                        try:
                            yield _ev("chart", chart=json.loads(p.read_text(encoding="utf-8")))
                        except ValueError:
                            pass
            elif t == "result":
                if ev.get("is_error") or ev.get("subtype") != "success":
                    msg = str(ev.get("result") or ev.get("subtype") or "The assistant stopped with an error.")
                    print(f"[chat] CLI run failed: {msg[:500]}", flush=True)
                    state["failed"] = True
                    if last:
                        yield _ev("error", text=msg)
                    break
                if not streamed and ev.get("result"):
                    yield _ev("text", text=ev["result"])
                yield _ev("done", seconds=round((ev.get("duration_ms") or 0) / 1000, 1), turns=ev.get("num_turns"))
                break
        if proc.returncode is None:
            try:
                await asyncio.wait_for(proc.wait(), timeout=5)
            except asyncio.TimeoutError:
                pass
        if proc.returncode not in (None, 0):
            err = (await proc.stderr.read()).decode(errors="replace").strip()
            print(f"[chat] CLI exit {proc.returncode}: {err[-1000:]}", flush=True)
            if not state["failed"]:
                state["failed"] = True
                if last and err:
                    yield _ev("error", text=f"Claude CLI: {err[-500:]}")
    finally:
        if proc is not None and proc.returncode is None:
            proc.kill()
            await proc.wait()
        shutil.rmtree(run_dir, ignore_errors=True)
