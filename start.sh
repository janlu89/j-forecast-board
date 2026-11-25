#!/bin/sh
# SPDX-License-Identifier: Apache-2.0
# Start J-Forecast Board on Linux. Options are passed on: ./start.sh --port 8010
# Settings come from JFB_* variables (docs/configuration.md), e.g. JFB_MODEL=stub ./start.sh
set -eu
cd "$(dirname "$0")"
if [ ! -x .venv/bin/python ]; then
    echo "J-Forecast Board is not installed yet: run ./setup.sh first." >&2
    exit 1
fi
export PYTHONUTF8=1
exec .venv/bin/python -m j_forecast_board serve "$@"
