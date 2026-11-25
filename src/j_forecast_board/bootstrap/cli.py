# SPDX-License-Identifier: Apache-2.0
"""Command line: `python -m j_forecast_board serve | doctor | password`."""

from __future__ import annotations

import argparse
import getpass
import os
import secrets
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
    _show_initial_password(config)
    print("Press Ctrl+C to stop.", flush=True)
    uvicorn.run(
        "j_forecast_board.bootstrap.app_factory:create_app",
        factory=True,
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

    code = checkup.run(args.mode, Path(args.out))
    _show_initial_password(settings.current())
    return code


def password(args: argparse.Namespace) -> int:
    """Set a new sign-in password (asked twice), or a random one with --generate."""
    from ..adapters.outbound.storage.file_secret_store import FileSecretStore
    from ..application.credentials import Credentials
    from .paths import RuntimePaths

    paths = RuntimePaths(settings.current().home)
    paths.create()
    credentials = Credentials(FileSecretStore(paths.secrets))
    if args.generate:
        new = secrets.token_urlsafe(12)
    else:
        new = getpass.getpass("New password: ")
        if getpass.getpass("Repeat it: ") != new:
            print("The two passwords differ: nothing changed.", file=sys.stderr)
            return 1
    try:
        credentials.set_password(new, user=args.user)
    except ValueError as error:
        print(error, file=sys.stderr)
        return 1
    shown = f" '{new}'" if args.generate else ""
    print(f"Password{shown} set for user '{credentials.user}'. Every open session has ended.")
    return 0


def _show_initial_password(config: settings.Settings) -> None:
    from .paths import RuntimePaths

    pending = RuntimePaths(config.home).secrets / "initial-password.txt"
    if pending.exists():
        first = pending.read_text(encoding="utf-8").strip()
        print(f"First sign-in: user 'admin', password '{first}' (shown until you sign in once).")


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

    password_parser = commands.add_parser("password", help="set a new sign-in password")
    password_parser.add_argument(
        "--generate", action="store_true", help="choose a random one and print it"
    )
    password_parser.add_argument("--user", help="also change the user name")
    password_parser.set_defaults(handler=password)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        apply_command_line(args)
        return args.handler(args)
    except settings.SettingsError as error:
        print(f"Configuration error: {error}", file=sys.stderr)
        return 2
