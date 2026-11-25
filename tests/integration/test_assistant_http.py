# SPDX-License-Identifier: Apache-2.0
"""The assistant over HTTP: off until set up, then a real answer from a fake local model server."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from fastapi.testclient import TestClient

from j_forecast_board.application.assistant.tools import Toolbox, ToolPermissions
from j_forecast_board.domain.errors import PolicyViolation


class FakeModelServer(BaseHTTPRequestHandler):
    """An OpenAI-compatible server: asks for one tool, then answers with text."""

    requests: list[dict] = []

    def log_message(self, *args):
        pass

    def _send(self, body: dict) -> None:
        raw = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):  # noqa: N802 - http.server's naming
        self._send({"data": [{"id": "fake-model"}]})

    def do_POST(self):  # noqa: N802
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        FakeModelServer.requests.append(body)
        if body["messages"][-1]["role"] == "user":
            call = {
                "id": "c1",
                "type": "function",
                "function": {"name": "accuracy_summary", "arguments": '{"dataset": "passengers"}'},
            }
            self._send({"choices": [{"message": {"content": "", "tool_calls": [call]}}]})
        else:
            self._send({"choices": [{"message": {"content": "Passengers: the model wins."}}]})


@pytest.fixture
def model_server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), FakeModelServer)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}/v1"
    server.shutdown()


@pytest.fixture
def browser(client):
    test_client = TestClient(client.app, raise_server_exceptions=False)
    test_client.auth = client.auth
    return test_client


def events(response) -> list[dict]:
    return [json.loads(line) for line in response.text.splitlines() if line.strip()]


def test_the_chat_answers_409_until_an_assistant_is_set_up(browser):
    browser.post("api/assistant/deactivate")
    response = browser.post("api/chat", json={"message": "Hi"})
    assert response.status_code == 409
    assert "No assistant is set up" in response.json()["error"]
    assert browser.get("api/assistant").json()["ready"] is False


def test_a_local_model_answers_with_a_tool_and_a_chart(browser, model_server, container):
    saved = browser.post(
        "api/assistant/agents/local", json={"model": "fake-model", "base_url": model_server}
    )
    assert saved.status_code == 200, saved.text
    tested = browser.post("api/assistant/agents/local/test", json={}).json()
    assert tested["ok"] and tested["models"] == ["fake-model"]
    active = browser.post("api/assistant/activate", json={"id": "local"}).json()
    assert active["ready"] and active["active"] == "local"

    page = {"tab": "Overview", "dataset": "passengers", "page_text": "MAPE 4%"}
    response = browser.post("api/chat", json={"message": "How good is it?", "context": page})
    assert response.status_code == 200
    stream = events(response)
    kinds = [e["type"] for e in stream]
    assert kinds[0] == "agent" and stream[0]["egress"] == "local"
    assert "chart" in kinds and kinds[-1] == "done"
    assert "Passengers: the model wins." in "".join(
        e["text"] for e in stream if e["type"] == "text"
    )
    tool_answer = FakeModelServer.requests[-1]["messages"][-1]
    assert tool_answer["role"] == "tool" and "Leaderboard" in tool_answer["content"]
    audit = container.audit.recent()
    assert audit[-1]["event"] == "assistant_call" and audit[-1]["tools"] == ["accuracy_summary"]
    browser.post("api/assistant/deactivate")


def test_internal_tool_routes_refuse_relayed_requests(browser):
    response = browser.get("internal/tools", headers={"X-Forwarded-For": "203.0.113.7"})
    assert response.status_code == 403


def test_internal_tool_routes_refuse_other_computers(browser):
    assert browser.get("internal/tools").status_code == 403  # the test client is not 127.0.0.1


def test_internal_tool_routes_need_an_open_answer(client):
    local = TestClient(client.app, raise_server_exceptions=False, client=("127.0.0.1", 50000))
    assert local.get("internal/tools", headers={"X-Tools-Token": "guess"}).status_code == 404
    response = local.post(
        "internal/tools/list_datasets", json={}, headers={"X-Tools-Token": "guess"}
    )
    assert response.status_code == 404


def test_the_toolbox_refuses_a_private_dataset_to_an_external_assistant(
    browser, container, repo_root
):
    sample = repo_root / "examples" / "sample_store_sales.csv"
    with sample.open("rb") as handle:
        uid = browser.post("api/upload", files={"file": (sample.name, handle, "text/csv")}).json()[
            "uid"
        ]
    spec = {
        "uid": uid,
        "date_col": "data",
        "target": "vendite",
        "id_col": "negozio",
        "name": "My shops",
    }
    meta = browser.post("api/upload/register", json=spec)
    assert meta.status_code == 200, meta.text
    key = meta.json()["key"]
    views = {
        name: getattr(container, name)
        for name in ("overview", "ranking", "planner", "live", "what_if", "anomalies")
    }
    toolbox = Toolbox(container.workbench, views)
    external = ToolPermissions(external=True)
    with pytest.raises(PolicyViolation, match="private data"):
        toolbox.call("forecast", {"dataset": key}, external)
    listing = toolbox.call("list_datasets", {}, external).text
    assert "My shops" not in listing and "private dataset(s)" in listing
    assert "My shops" in toolbox.call("list_datasets", {}, ToolPermissions(external=False)).text
