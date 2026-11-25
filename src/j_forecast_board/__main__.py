# SPDX-License-Identifier: Apache-2.0
"""`python -m j_forecast_board <command>` (see bootstrap/cli.py)."""

import sys

from .bootstrap.cli import main

if __name__ == "__main__":
    sys.exit(main())
