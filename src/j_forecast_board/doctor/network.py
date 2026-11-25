# SPDX-License-Identifier: Apache-2.0
"""Which public hosts this PC can reach. A failure here is a warning: an offline install exists."""

from __future__ import annotations

import os
import ssl
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

from .report import OK, WARN, Check, run_check

USER_AGENT = "j-forecast-board-doctor/0.1"
TIMEOUT_SECONDS = 10
HOSTS = {  # check id -> (URL, what it is needed for)
    "pypi.org": ("https://pypi.org/simple/pip/", "installing packages"),
    "download.pytorch.org": ("https://download.pytorch.org/whl/cpu/", "installing torch (CPU)"),
    "github.com": ("https://github.com/mistralai/timestral", "installing timestral"),
    "codeload.github.com": (
        "https://codeload.github.com/mistralai/timestral/zip/a534bdbd244d64f3d9d743f46c7bf6fc330ed4ff",
        "installing timestral",
    ),
    "huggingface.co": (
        "https://huggingface.co/api/models/mistralai/Timestral-28M",
        "downloading the model weights",
    ),
    "raw.githubusercontent.com": (
        "https://raw.githubusercontent.com/jbrownlee/Datasets/master/airline-passengers.csv",
        "downloading most built-in datasets",
    ),
    "archive.ics.uci.edu": (
        "https://archive.ics.uci.edu/static/public/275/bike+sharing+dataset.zip",
        "downloading the bike sharing dataset",
    ),
}
PROXY_VARIABLES = (
    "HTTPS_PROXY", "HTTP_PROXY", "NO_PROXY", "PIP_INDEX_URL", "PIP_CERT",
    "REQUESTS_CA_BUNDLE", "SSL_CERT_FILE", "HF_ENDPOINT",
)  # fmt: skip


def network_checks() -> list[Check]:
    with ThreadPoolExecutor(max_workers=len(HOSTS)) as pool:
        checks = list(
            pool.map(
                lambda item: run_check("network", item[0], lambda: _reach(*item[1])), HOSTS.items()
            )
        )
    return [run_check("network", "proxy", _proxy_settings), *checks]


def _proxy_settings() -> Check:
    seen = {name: "set" if _variable_set(name) else "not set" for name in PROXY_VARIABLES}
    used = [name for name, state in seen.items() if state == "set"]
    message = f"set: {', '.join(used)}" if used else "no proxy or certificate variable set"
    return Check("", "", OK, message, details=seen)


def _variable_set(name: str) -> bool:
    return bool(os.environ.get(name) or os.environ.get(name.lower()))


def _reach(url: str, purpose: str) -> Check:
    # HEAD: any HTTP answer proves the host is reachable, and nothing large is downloaded
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT}, method="HEAD")
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            status = response.status
    except urllib.error.HTTPError as error:
        status = error.code  # the host answered: it is reachable
    except urllib.error.URLError as error:
        return _unreachable(purpose, error.reason)
    except (TimeoutError, OSError) as error:
        return _unreachable(purpose, error)
    return Check(
        "", "", OK, f"reachable (HTTP {status}), needed for {purpose}", details=dict(http=status)
    )


def _unreachable(purpose: str, reason) -> Check:
    if isinstance(reason, ssl.SSLCertVerificationError) or "CERTIFICATE_VERIFY_FAILED" in str(
        reason
    ):
        fix = (
            "The company network inspects HTTPS. Ask IT for the root certificate and set "
            "SSL_CERT_FILE and PIP_CERT to it, or use the offline bundle."
        )
        kind = "certificate not trusted"
    elif isinstance(reason, TimeoutError) or "timed out" in str(reason):
        fix = "Blocked or slow: set HTTPS_PROXY to the company proxy, or use the offline bundle."
        kind = "timed out"
    else:
        fix = "Set HTTPS_PROXY if the network needs a proxy, or use the offline bundle."
        kind = type(reason).__name__ if not isinstance(reason, str) else reason
    return Check("", "", WARN, f"not reachable ({kind}), needed for {purpose}", fix)
