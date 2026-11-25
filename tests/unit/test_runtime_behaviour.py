# SPDX-License-Identifier: Apache-2.0
"""Downloads of the public datasets: offline mode, and no half-written file after a crash."""

from __future__ import annotations

import pytest

from j_forecast_board.adapters.outbound.datasets import downloader as module
from j_forecast_board.adapters.outbound.datasets.downloader import Downloader


def test_offline_mode_refuses_to_download_a_dataset(tmp_path):
    with pytest.raises(RuntimeError, match="JFB_OFFLINE=1"):
        Downloader(tmp_path, offline=True).fetch("https://example.invalid/data.csv", "data.csv")


def test_offline_mode_still_reads_a_downloaded_dataset(tmp_path):
    (tmp_path / "data.csv").write_bytes(b"a,b\n1,2\n")
    assert (
        Downloader(tmp_path, offline=True).fetch("https://example.invalid/x", "data.csv")
        == b"a,b\n1,2\n"
    )


def test_a_failed_download_leaves_no_file(tmp_path, monkeypatch):
    def unreachable(*args, **kwargs):
        raise OSError("network down")

    monkeypatch.setattr(module.urllib.request, "urlopen", unreachable)
    monkeypatch.setattr(module.time, "sleep", lambda seconds: None)
    with pytest.raises(RuntimeError, match="Download failed"):
        Downloader(tmp_path, offline=False).fetch("https://example.invalid/x", "data.csv")
    assert list(tmp_path.iterdir()) == []
