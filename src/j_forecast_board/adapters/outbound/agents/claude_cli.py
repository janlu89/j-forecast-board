# SPDX-License-Identifier: Apache-2.0
"""Claude Code CLI as the assistant, locked down to the app's tools only.

The CLI runs with no built-in tools (--tools ""), only our MCP server allowed, no user settings or
hooks, in an empty temporary folder. Prompts travel through stdin and the system prompt through a
file, never as command-line text (Windows .cmd shims mangle it). A blocking subprocess read by a
helper thread: no asyncio subprocess, so it behaves the same on Windows and Linux.
"""

from __future__ import annotations

import json
import os
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

from ....application.assistant.ports import (
    AgentConfig,
    AgentKind,
    AgentOutcome,
    AgentRequest,
    CheckResult,
    Emit,
    ToolSession,
)
from ....application.assistant.tools import LABELS
from ....domain.errors import UpstreamError

EXECUTABLE = "claude"
MAX_TURNS = 12
MCP_MODULE = "j_forecast_board.adapters.inbound.mcp_stdio"
KIND = AgentKind(
    "claude-cli",
    "Claude Code CLI",
    "Anthropic",
    "Claude Code installed on this PC and signed in (claude login). It answers with Anthropic's "
    "models: the question and the page you look at are sent to Anthropic. It can use only this "
    "app's forecasting tools: no files, no shell.",
    needs_cli=EXECUTABLE,
    models=("sonnet", "opus", "haiku"),
)


class ClaudeCliAgent:
    kind = KIND

    def __init__(self, executable: str | None = None):
        self._executable = executable

    def _path(self) -> str | None:
        return self._executable or shutil.which(EXECUTABLE)

    def check(self, config: AgentConfig) -> CheckResult:
        path = self._path()
        if path is None:
            return CheckResult(
                False,
                "Claude Code CLI not found on PATH. Install it, run 'claude login', then test "
                "again.",
            )
        return CheckResult(True, f"Claude Code CLI found: {path}", list(KIND.models))

    def ask(
        self, config: AgentConfig, request: AgentRequest, tools: ToolSession, emit: Emit
    ) -> AgentOutcome:
        path = self._path()
        if path is None:
            raise UpstreamError("The Claude Code CLI is not installed on this PC.")
        for attempt in (1, 2):
            try:
                return self._run(path, config, request, tools, emit)
            except _RetryableFailure as failure:
                if attempt == 2 or time.monotonic() > request.deadline:
                    raise UpstreamError(str(failure)) from None
                emit("reset", text="The assistant stopped unexpectedly, retrying once…")
        raise AssertionError("unreachable")

    def _run(
        self, path, config: AgentConfig, request: AgentRequest, tools: ToolSession, emit: Emit
    ) -> AgentOutcome:
        with tempfile.TemporaryDirectory(prefix="jfb-chat-") as folder:
            run_dir = Path(folder)
            if os.name != "nt":
                run_dir.chmod(0o700)
            command = [path, *self._arguments(run_dir, config, request, tools)]
            process = subprocess.Popen(
                command,
                cwd=run_dir,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            try:
                return _Reader(process, request, emit).follow(request.prompt)
            finally:
                if process.poll() is None:
                    process.kill()
                process.wait()

    def _arguments(
        self, run_dir: Path, config: AgentConfig, request: AgentRequest, tools: ToolSession
    ) -> list[str]:
        url, token = tools.remote()
        mcp = {
            "mcpServers": {
                "forecaster": {
                    "type": "stdio",
                    "command": sys.executable,
                    "args": ["-m", MCP_MODULE],
                    "env": {"JFB_TOOLS_URL": url, "JFB_TOOLS_TOKEN": token},
                }
            }
        }
        _private_file(run_dir / "mcp.json", json.dumps(mcp))
        _private_file(run_dir / "system.txt", request.system)
        return [
            "-p",
            "--output-format",
            "stream-json",
            "--verbose",
            "--include-partial-messages",
            "--model",
            config.model or KIND.models[0],
            "--tools",
            "",
            "--strict-mcp-config",
            "--mcp-config",
            str(run_dir / "mcp.json"),
            "--allowedTools",
            "mcp__forecaster",
            "--permission-mode",
            "dontAsk",
            "--setting-sources",
            "project",
            "--disable-slash-commands",
            "--no-session-persistence",
            "--max-turns",
            str(MAX_TURNS),
            "--system-prompt-file",
            str(run_dir / "system.txt"),
        ]


class _RetryableFailure(Exception):
    pass


class _Reader:
    """Follows the CLI's stream-json output until the result event, the deadline or the exit."""

    def __init__(self, process: subprocess.Popen, request: AgentRequest, emit: Emit):
        self._process = process
        self._deadline = request.deadline
        self._emit = emit
        self._lines: queue.Queue = queue.Queue()
        self._streamed = False

    def follow(self, prompt: str) -> AgentOutcome:
        self._process.stdin.write(prompt.encode("utf-8"))
        self._process.stdin.close()
        threading.Thread(target=self._pump, daemon=True).start()
        self._emit("status", text="Thinking…")
        while True:
            left = self._deadline - time.monotonic()
            if left <= 0:
                raise TimeoutError
            try:
                line = self._lines.get(timeout=min(left, 1.0))
            except queue.Empty:
                continue
            if line is None:
                break
            outcome = self._handle(line)
            if outcome is not None:
                return outcome
        error = self._process.stderr.read().decode(errors="replace").strip()
        raise _RetryableFailure(
            f"Claude CLI stopped (exit {self._process.wait()}): {error[-500:] or 'no details'}"
        )

    def _pump(self) -> None:
        for line in self._process.stdout:
            self._lines.put(line)
        self._lines.put(None)

    def _handle(self, line: bytes) -> AgentOutcome | None:
        try:
            event = json.loads(line)
        except ValueError:
            return None
        kind = event.get("type")
        if kind == "stream_event":
            inner = event.get("event", {})
            delta = inner.get("delta", {})
            if inner.get("type") == "content_block_delta" and delta.get("type") == "text_delta":
                self._streamed = True
                self._emit("text", text=delta.get("text", ""))
            elif inner.get("type") == "message_start" and self._streamed:
                self._emit("text", text="\n\n")  # a new assistant turn after tool calls
        elif kind == "assistant":
            for block in event.get("message", {}).get("content", []):
                if block.get("type") == "tool_use":
                    name = block.get("name", "").split("__")[-1]
                    label = LABELS.get(name, f"Using {name}")
                    self._emit("status", text=f"{label}…", tool=name, input=block.get("input"))
        elif kind == "result":
            if event.get("is_error") or event.get("subtype") != "success":
                raise _RetryableFailure(
                    str(
                        event.get("result")
                        or event.get("subtype")
                        or "The assistant stopped with an error."
                    )
                )
            if not self._streamed and event.get("result"):
                self._emit("text", text=event["result"])
            return AgentOutcome(
                turns=event.get("num_turns") or 1,
                seconds=round((event.get("duration_ms") or 0) / 1000, 1),
            )
        return None


def _private_file(path: Path, content: str) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(content)
