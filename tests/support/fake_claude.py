# SPDX-License-Identifier: Apache-2.0
"""A stand-in for the `claude` CLI used by tests: same flags, same stream-json output.

It starts the MCP server named in --mcp-config, lists the tools, calls one, and answers with a
text that says what it saw, so a test can check the whole path without the real CLI.
"""

import json
import os
import subprocess
import sys


def option(args: list[str], name: str) -> str:
    return args[args.index(name) + 1]


def main() -> None:
    args = sys.argv[1:]
    assert option(args, "--tools") == ""
    with open(option(args, "--mcp-config"), encoding="utf-8") as handle:
        server = json.load(handle)["mcpServers"]["forecaster"]
    with open(option(args, "--system-prompt-file"), encoding="utf-8") as handle:
        system = handle.read()
    prompt = sys.stdin.read()
    mcp = subprocess.Popen(
        [server["command"], *server["args"]],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        env={**os.environ, **server["env"]},
        text=True,
    )

    def rpc(number: int, method: str, params: dict) -> dict:
        message = dict(jsonrpc="2.0", id=number, method=method, params=params)
        mcp.stdin.write(json.dumps(message) + "\n")
        mcp.stdin.flush()
        return json.loads(mcp.stdout.readline())

    def say(event: dict) -> None:
        print(json.dumps(event), flush=True)

    rpc(1, "initialize", {})
    tools = rpc(2, "tools/list", {})["result"]["tools"]
    arguments = {"dataset": "passengers"}
    use = {"type": "tool_use", "name": "mcp__forecaster__accuracy_summary", "input": arguments}
    say({"type": "assistant", "message": {"content": [use]}})
    call = {"name": "accuracy_summary", "arguments": arguments}
    result = rpc(3, "tools/call", call)["result"]
    mcp.stdin.close()
    seen = f"system {'J-Forecast Board' in system}; question {'How good' in prompt}"
    text = f"{len(tools)} tools; {seen}; " + result["content"][0]["text"].split(":")[0]
    delta = {"type": "text_delta", "text": text}
    say({"type": "stream_event", "event": {"type": "content_block_delta", "delta": delta}})
    say(
        {"type": "result", "subtype": "success", "num_turns": 2, "duration_ms": 900, "result": text}
    )


if __name__ == "__main__":
    main()
