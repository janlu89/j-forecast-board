# SPDX-License-Identifier: Apache-2.0
"""Checks of the PC itself: system, Python, packages, folders, port, model weights, CLIs."""

from __future__ import annotations

import ctypes
import importlib
import importlib.metadata
import locale
import os
import platform
import shutil
import socket
import subprocess
import sys
import tempfile
from pathlib import Path

from ..paths import RuntimePaths
from ..settings import MODEL_SIZES, Settings
from .report import FAIL, OK, WARN, Check, run_check

GIB = 1024**3
RUNTIME_PACKAGES = {  # import name -> distribution name
    "fastapi": "fastapi",
    "uvicorn": "uvicorn",
    "multipart": "python-multipart",
    "pandas": "pandas",
    "numpy": "numpy",
    "holidays": "holidays",
    "torch": "torch",
    "timestral": "timestral",
    "huggingface_hub": "huggingface-hub",
}
OPTIONAL_CLIS = ("copilot", "claude", "git")
REINSTALL = "Run the setup script again (setup.ps1 on Windows, setup.sh on Linux)."


def environment_checks(config: Settings, paths: RuntimePaths) -> list[Check]:
    checks = [
        run_check("system", "os", _os),
        run_check("system", "cpu", _cpu),
        run_check("system", "memory", _memory),
        run_check("system", "disk", lambda: _disk(paths.home)),
        run_check("python", "version", _python_version),
        run_check("python", "venv", _venv),
        run_check("python", "encoding", _encoding),
    ]
    checks += [
        run_check("packages", module, lambda m=module, d=dist: _package(m, d))
        for module, dist in RUNTIME_PACKAGES.items()
    ]
    checks += [
        run_check("paths", "home", lambda: _writable(paths)),
        run_check("paths", "port", lambda: _port_free(config.host, config.port)),
        run_check("model", "weights", lambda: _weights(config)),
    ]
    checks += [run_check("clis", name, lambda n=name: _cli(n)) for name in OPTIONAL_CLIS]
    return checks


# ----------------------------------------------------------------------------- system
def _os() -> Check:
    details = dict(system=platform.system(), release=platform.release(), machine=platform.machine())
    supported = platform.system() in ("Windows", "Linux")
    return Check(
        "", "", OK if supported else WARN,
        f"{platform.system()} {platform.release()} on {platform.machine()}",
        "" if supported else "Windows 10/11 and Linux are tested; this system is not.",
        details,
    )  # fmt: skip


def _cpu() -> Check:
    cores = os.cpu_count() or 1
    status = OK if cores >= 2 else WARN
    return Check("", "", status, f"{cores} CPU cores", "Forecasts will be slow on one core.")


def _memory() -> Check:
    total = _total_memory()
    if total is None:
        return Check("", "", WARN, "total memory unknown")
    status = OK if total >= 4 * GIB else WARN
    fix = "4 GB or more is recommended; close other programs during evaluations."
    return Check("", "", status, f"{total / GIB:.1f} GB RAM", fix, dict(gib=round(total / GIB, 1)))


def _total_memory() -> int | None:
    if os.name == "nt":
        return _windows_total_memory()
    try:
        with open("/proc/meminfo", encoding="ascii") as meminfo:
            for line in meminfo:
                if line.startswith("MemTotal:"):
                    return int(line.split()[1]) * 1024
    except OSError:
        return None
    return None


def _windows_total_memory() -> int | None:
    class MemoryStatus(ctypes.Structure):
        _fields_ = [  # ctypes layout of MEMORYSTATUSEX
            ("length", ctypes.c_ulong),
            ("load", ctypes.c_ulong),
            ("total_physical", ctypes.c_ulonglong),
            ("available_physical", ctypes.c_ulonglong),
            ("total_page_file", ctypes.c_ulonglong),
            ("available_page_file", ctypes.c_ulonglong),
            ("total_virtual", ctypes.c_ulonglong),
            ("available_virtual", ctypes.c_ulonglong),
            ("available_extended_virtual", ctypes.c_ulonglong),
        ]

    status = MemoryStatus()
    status.length = ctypes.sizeof(MemoryStatus)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
        return None
    return int(status.total_physical)


def _disk(home: Path) -> Check:
    existing = home
    while not existing.exists() and existing.parent != existing:
        existing = existing.parent
    free = shutil.disk_usage(existing).free
    status = FAIL if free < 1 * GIB else WARN if free < 3 * GIB else OK
    fix = "About 3 GB are needed (packages, model weights, datasets). Free some disk space."
    return Check("", "", status, f"{free / GIB:.1f} GB free for the runtime folder", fix)


# ----------------------------------------------------------------------------- python
def _python_version() -> Check:
    version = platform.python_version()
    supported = (3, 12) <= sys.version_info[:2] < (3, 15)
    return Check(
        "", "", OK if supported else FAIL, f"Python {version} ({platform.python_implementation()})",
        "Install Python 3.12, 3.13 or 3.14 from python.org, then run the setup script again.",
        dict(version=version, executable=sys.executable),
    )  # fmt: skip


def _venv() -> Check:
    inside = sys.prefix != sys.base_prefix
    message = "running inside a virtual environment" if inside else "not in a virtual environment"
    return Check(
        "", "", OK if inside else WARN, message,
        "Start the app with the start script, which uses the .venv folder created by setup.",
        dict(prefix=sys.prefix),
    )  # fmt: skip


def _encoding() -> Check:
    stream = (getattr(sys.stdout, "encoding", None) or "unknown").lower()
    utf8 = sys.flags.utf8_mode or stream.replace("-", "") == "utf8"
    details = dict(
        stdout=stream, utf8_mode=bool(sys.flags.utf8_mode), locale=locale.getpreferredencoding()
    )
    return Check(
        "", "", OK if utf8 else WARN, f"console encoding {stream}",
        "Set PYTHONUTF8=1 (the start scripts do it), or some symbols print as '?'.", details,
    )  # fmt: skip


def _package(module: str, distribution: str) -> Check:
    try:
        imported = importlib.import_module(module)
    except Exception as error:
        return Check("", "", FAIL, f"cannot import {module}: {error}", REINSTALL)
    version = importlib.metadata.version(distribution)
    details = dict(version=version)
    if module == "torch":
        details.update(threads=imported.get_num_threads(), cuda=bool(imported.cuda.is_available()))
    return Check("", "", OK, f"{distribution} {version}", details=details)


# ----------------------------------------------------------------------------- paths
def _writable(paths: RuntimePaths) -> Check:
    paths.create()
    with tempfile.NamedTemporaryFile(dir=paths.home, prefix=".doctor-", delete=True) as probe:
        probe.write(b"ok")
    return Check(
        "", "", OK, f"runtime folder writable: {paths.home}", details=dict(path=str(paths.home))
    )


def _port_free(host: str, port: int) -> Check:
    with socket.socket(socket.AF_INET6 if ":" in host else socket.AF_INET) as probe:
        try:
            probe.bind((host, port))
        except OSError as error:
            return Check(
                "", "", WARN, f"port {port} on {host} is in use ({error.strerror})",
                f"Another program uses port {port}: stop it, or start with another port "
                "(start.ps1 -Port 8010, or JFB_PORT=8010).",
            )  # fmt: skip
    return Check("", "", OK, f"port {port} on {host} is free")


# ----------------------------------------------------------------------------- model
def _weights(config: Settings) -> Check:
    from huggingface_hub import try_to_load_from_cache

    cached = [
        size
        for size in MODEL_SIZES
        if isinstance(
            try_to_load_from_cache(f"mistralai/Timestral-{size}", "model.safetensors"), str
        )
    ]
    details = dict(cached=cached, default=config.default_model_size)
    if config.default_model_size in cached:
        return Check(
            "", "", OK, f"weights in the local cache: {', '.join(cached)}", details=details
        )
    return Check(
        "", "", WARN, f"Timestral-{config.default_model_size} weights are not downloaded yet",
        "They download from Hugging Face at the first real forecast. Read the weights licence in "
        "the README first. Tests and checks work without them (JFB_MODEL=stub).",
        details,
    )  # fmt: skip


# ----------------------------------------------------------------------------- clis
def _cli(name: str) -> Check:
    executable = shutil.which(name)
    if executable is None:
        return Check("", "", OK, f"{name}: not installed (optional)", details=dict(found=False))
    try:
        result = subprocess.run(
            [executable, "--version"], capture_output=True, text=True, timeout=20, check=False
        )
        version = (result.stdout or result.stderr).strip().splitlines()[0][:80]
    except (OSError, subprocess.TimeoutExpired, IndexError) as error:
        version = f"version unknown ({type(error).__name__})"
    if "not found" in version.lower() or "not installed" in version.lower():
        message = f"{name}: not installed (optional; only a launcher is on PATH)"
        return Check("", "", OK, message, details=dict(found=False, launcher=executable))
    return Check("", "", OK, f"{name}: {version}", details=dict(found=True, path=executable))
