# SPDX-License-Identifier: Apache-2.0
"""The CLI assistant end to end, with a fake `claude` executable (tests/support/fake_claude.py).

The tool call travels: MCP server -> /internal/tools on the running app -> the toolbox of the open
answer, and its chart reaches the page.
"""

from __future__ import annotations

import base64
import json
import os
import shutil
import socket
import sys
import threading
import time
import urllib.request
from pathlib import Path

import pytest

from j_forecast_board.adapters.outbound.agents.claude_cli import ClaudeCliAgent
from j_forecast_board.adapters.outbound.datasets.builtin import passengers
from j_forecast_board.bootstrap.app_factory import create_app
from j_forecast_board.bootstrap.container import build
from j_forecast_board.bootstrap.settings import Settings

FAKE_CLI = Path(__file__).resolve().parents[1] / "support" / "fake_claude.py"


@pytest.fixture
def running_app(tmp_path, repo_root):
    import uvicorn

    home = tmp_path / "home"
    shutil.copytree(repo_root / "tests" / "golden" / "fixtures", home)
    settings = Settings(home=home, offline=True, background_eval=False)
    container = build(settings, loaders={"passengers": passengers.load})
    fake = tmp_path / "claude"
    fake.write_text(
        f"#!{sys.executable}\n" + FAKE_CLI.read_text(encoding="utf-8"), encoding="utf-8"
    )
    fake.chmod(0o755)
    container.assistant_agents["claude-cli"] = ClaudeCliAgent(executable=str(fake))
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    server = uvicorn.Server(
        uvicorn.Config(create_app(container), host="127.0.0.1", port=port, log_level="warning")
    )
    threading.Thread(target=server.run, daemon=True).start()
    while not server.started:
        time.sleep(0.05)
    password = (home / "secrets" / "initial-password.txt").read_text().strip()
    yield f"http://127.0.0.1:{port}", base64.b64encode(f"admin:{password}".encode()).decode()
    server.should_exit = True


def call(app, path, body=None):
    url, token = app
    request = urllib.request.Request(
        f"{url}/{path}",
        data=None if body is None else json.dumps(body).encode(),
        headers={"Authorization": f"Basic {token}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read()


@pytest.mark.skipif(os.name == "nt", reason="the fake CLI is a POSIX script")
def test_a_cli_assistant_uses_only_our_tools_and_its_chart_reaches_the_page(running_app):
    call(running_app, "api/assistant/agents/claude-cli", {"model": "sonnet"})
    assert json.loads(call(running_app, "api/assistant/agents/claude-cli/test", {}))["ok"]
    listing = json.loads(
        call(running_app, "api/assistant/activate", {"id": "claude-cli", "consent": True})
    )
    assert listing["ready"]
    raw = call(
        running_app,
        "api/chat",
        {"message": "How good is it?", "context": {"dataset": "passengers"}},
    )
    events = [json.loads(line) for line in raw.decode().splitlines() if line.strip()]
    kinds = [e["type"] for e in events]
    assert (
        kinds[0] == "agent"
        and events[0]["egress"] == "external"
        and events[0]["destination"] == "Anthropic"
    )
    assert "chart" in kinds and kinds[-1] == "done"
    text = "".join(e["text"] for e in events if e["type"] == "text")
    assert text == "7 tools; system True; question True; Dataset Airline passengers · monthly"
