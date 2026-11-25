# SPDX-License-Identifier: Apache-2.0
"""Command line entry point: `python -m j_forecast_board <command>`."""

from __future__ import annotations

import argparse
import os
import sys

from . import settings


def serve(args: argparse.Namespace) -> int:
    """Run the web app in the foreground until Ctrl+C."""
    import uvicorn

    config = settings.current()
    uvicorn.run(
        "j_forecast_board.server:app",
        host=config.host,
        port=config.port,
        root_path=config.root_path,
        proxy_headers=config.trust_proxy,
        log_level=config.log_level,
    )
    return 0


def apply_command_line(args: argparse.Namespace) -> None:
    """Command line options win over JFB_* variables; offline mode also covers Hugging Face."""
    if getattr(args, "host", None):
        os.environ["JFB_HOST"] = args.host
    if getattr(args, "port", None):
        os.environ["JFB_PORT"] = str(args.port)
    if settings.current().offline:
        os.environ["HF_HUB_OFFLINE"] = "1"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m j_forecast_board")
    commands = parser.add_subparsers(dest="command", required=True)
    serve_parser = commands.add_parser("serve", help="start the web app")
    serve_parser.add_argument(
        "--host", help="address to listen on (default: JFB_HOST or 127.0.0.1)"
    )
    serve_parser.add_argument("--port", type=int, help="port (default: JFB_PORT or 8000)")
    serve_parser.set_defaults(handler=serve)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        apply_command_line(args)
        return args.handler(args)
    except settings.SettingsError as error:
        print(f"Configuration error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
