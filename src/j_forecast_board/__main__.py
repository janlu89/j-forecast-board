# SPDX-License-Identifier: Apache-2.0
"""Command line entry point: `python -m j_forecast_board <command>`."""

from __future__ import annotations

import argparse
import sys


def serve(args: argparse.Namespace) -> int:
    """Run the web app in the foreground until Ctrl+C."""
    import uvicorn

    uvicorn.run("j_forecast_board.server:app", host=args.host, port=args.port, proxy_headers=True)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m j_forecast_board")
    commands = parser.add_subparsers(dest="command", required=True)
    serve_parser = commands.add_parser("serve", help="start the web app")
    serve_parser.add_argument("--host", default="127.0.0.1")
    serve_parser.add_argument("--port", type=int, default=8000)
    serve_parser.set_defaults(handler=serve)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.handler(args)


if __name__ == "__main__":
    sys.exit(main())
