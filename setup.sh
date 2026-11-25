#!/bin/sh
# SPDX-License-Identifier: Apache-2.0
# First-time setup on Linux: create .venv, install the pinned dependencies, check the result.
# Usage: ./setup.sh        To choose the interpreter: JFB_PYTHON=/usr/bin/python3.13 ./setup.sh
set -eu
cd "$(dirname "$0")"

supported() {
    "$1" -c 'import sys; sys.exit(0 if (3, 12) <= sys.version_info[:2] < (3, 15) else 1)' 2>/dev/null
}

find_python() {
    for candidate in ${JFB_PYTHON:-} python3.14 python3.13 python3.12 python3 python; do
        if command -v "$candidate" >/dev/null 2>&1 && supported "$candidate"; then
            command -v "$candidate"
            return 0
        fi
    done
    return 1
}

if ! PYTHON=$(find_python); then
    echo "Python 3.12, 3.13 or 3.14 is needed. Install it, for example:" >&2
    echo "  sudo apt install python3.12 python3.12-venv" >&2
    echo "then run ./setup.sh again." >&2
    exit 1
fi
echo "Using $("$PYTHON" --version) from $PYTHON"

if [ -x .venv/bin/python ] && ! supported .venv/bin/python; then
    echo "The existing .venv uses an unsupported Python. Delete the .venv folder and run ./setup.sh again." >&2
    exit 1
fi
if [ ! -x .venv/bin/python ]; then
    if ! "$PYTHON" -m venv .venv; then
        echo "Could not create .venv. On Debian or Ubuntu: sudo apt install python3-venv" >&2
        exit 1
    fi
fi

.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m pip install --no-deps --no-build-isolation --editable .

echo
echo "Checking the installation. The first time this also downloads the public datasets."
if PYTHONUTF8=1 .venv/bin/python -m j_forecast_board doctor --no-model; then
    echo
    echo "Setup finished. Start the app with: ./start.sh"
else
    echo
    echo "Setup finished, but the check found problems: read diagnostics/doctor-report.txt." >&2
    exit 1
fi
