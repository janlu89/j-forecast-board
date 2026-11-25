# SPDX-License-Identifier: Apache-2.0
"""MCP server started by a CLI assistant for one answer. Standard library only.

It knows nothing about forecasting: it forwards every tool call to the running app on loopback
(JFB_TOOLS_URL), authorised by the token of that one answer (JFB_TOOLS_TOKEN). The app runs the
tool with the answer's permissions and shows any chart to the user itself.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

PROTOCOL = "2025-06-18"
TIMEOUT = 600
TOKEN_HEADER = "X-Tools-Token"


class Forwarder:
    def __init__(self, url: str, token: str):
        self._url = url.rstrip("/")
        self._token = token

    def request(self, path: str, body: dict | None = None) -> dict:
        data = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(
            f"{self._url}/internal/tools{path}",
            data=data,
            method="POST" if data is not None else "GET",
            headers={"Content-Type": "application/json", TOKEN_HEADER: self._token},
        )
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
                return json.loads(response.read())
        except urllib.error.HTTPError as error:
            try:
                return json.loads(error.read())
            except ValueError:
                return {"error": f"HTTP {error.code}"}
        except (urllib.error.URLError, OSError) as error:
            return {"error": f"The app is not reachable: {error}"}


def handle(message: dict, forwarder: Forwarder) -> dict | None:
    method, message_id = message.get("method"), message.get("id")
    if message_id is None:  # a notification needs no answer
        return None
    if method == "initialize":
        version = message.get("params", {}).get("protocolVersion", PROTOCOL)
        result = dict(
            protocolVersion=version,
            capabilities={"tools": {}},
            serverInfo={"name": "j-forecast-board", "version": "0.1"},
        )
    elif method == "tools/list":
        listing = forwarder.request("")
        if "error" in listing:
            return _error(message_id, -32603, listing["error"])
        result = dict(tools=listing["tools"])
    elif method == "tools/call":
        params = message.get("params", {})
        answer = forwarder.request(f"/{params.get('name', '')}", params.get("arguments") or {})
        if "error" in answer:
            result = dict(
                content=[dict(type="text", text=f"Error: {answer['error']}")], isError=True
            )
        else:
            result = dict(content=[dict(type="text", text=answer["text"])])
    elif method == "ping":
        result = {}
    else:
        return _error(message_id, -32601, f"Method not found: {method}")
    return dict(jsonrpc="2.0", id=message_id, result=result)


def _error(message_id, code: int, text: str) -> dict:
    return dict(jsonrpc="2.0", id=message_id, error=dict(code=code, message=text))


def main() -> int:
    forwarder = Forwarder(
        os.environ.get("JFB_TOOLS_URL", ""), os.environ.get("JFB_TOOLS_TOKEN", "")
    )
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            answer = handle(json.loads(line), forwarder)
        except Exception as error:  # never die on a bad message
            answer = _error(None, -32603, str(error))
        if answer is not None:
            sys.stdout.write(json.dumps(answer) + "\n")
            sys.stdout.flush()
    return 0
