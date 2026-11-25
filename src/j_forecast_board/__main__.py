# SPDX-License-Identifier: Apache-2.0
"""Command line entry point: `python -m j_forecast_board <command>`."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from . import settings


def serve(args: argparse.Namespace) -> int:
    """Run the web app in the foreground until Ctrl+C."""
    import uvicorn

    config = settings.current()
    shown_host = "localhost" if config.host in ("127.0.0.1", "::1") else config.host
    address = f"http://{shown_host}:{config.port}{config.root_path}/"
    print(f"J-Forecast Board: open {address} in the browser.")
    if config.model == "stub":
        print("Model: stub (a stand-in for tests; its numbers are not forecasts).")
    print("Press Ctrl+C to stop.", flush=True)
    uvicorn.run(
        "j_forecast_board.server:app",
        host=config.host,
        port=config.port,
        root_path=config.root_path,
        proxy_headers=config.trust_proxy,
        log_level=config.log_level,
    )
    return 0


def doctor(args: argparse.Namespace) -> int:
    """Check this PC and write diagnostics/doctor-report.{json,txt}."""
    from . import doctor as checkup

    return checkup.run(args.mode, Path(args.out))


def apply_command_line(args: argparse.Namespace) -> None:
    """Command line options win over JFB_* variables; offline mode also covers Hugging Face."""
    if args.command == "doctor":
        from . import doctor as checkup

        checkup.prepare_environment(args.mode)
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

    doctor_parser = commands.add_parser("doctor", help="check this PC and write a report")
    modes = doctor_parser.add_mutually_exclusive_group()
    modes.add_argument(
        "--no-model", dest="mode", action="store_const", const="no-model",
        help="also start the app on the stub model and call every route",
    )  # fmt: skip
    modes.add_argument(
        "--with-model", dest="mode", action="store_const", const="with-model",
        help="like --no-model, plus one real Timestral forecast (may download the weights)",
    )  # fmt: skip
    doctor_parser.add_argument("--out", default="diagnostics", help="report folder")
    doctor_parser.set_defaults(handler=doctor, mode="basic")
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
