# SPDX-License-Identifier: Apache-2.0
"""Mistral AI's Timestral models, loaded from the Hugging Face cache (downloaded
once if allowed)."""

from __future__ import annotations

import os
import time
import warnings

from ....domain.errors import ModelUnavailable
from .batched import BatchedQuantileModel

DOWNLOAD_ATTEMPTS = 10  # the connection to huggingface.co can be flaky
WEIGHTS_FILE = "model.safetensors"


class TimestralModel(BatchedQuantileModel):
    def __init__(self, offline: bool):
        super().__init__()
        self._offline = offline
        os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

    def is_available(self, repo: str) -> bool:
        try:
            from huggingface_hub import try_to_load_from_cache

            return isinstance(try_to_load_from_cache(repo, WEIGHTS_FILE), str)
        except Exception:  # a broken cache means "not available", never a crash
            return False

    def output_block(self, repo: str) -> int | None:
        forecaster = self.forecaster(repo)
        try:
            return int(forecaster.per_shot_horizon_patches) * int(
                forecaster.model.config.patch_size
            )
        except (AttributeError, TypeError, ValueError):
            return None

    def _load(self, repo: str):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            from timestral import TimestralForecaster

            try:
                return TimestralForecaster.from_pretrained(
                    repo, device="cpu", local_files_only=True
                )
            except Exception as error:
                if self._offline:
                    raise ModelUnavailable(
                        f"Offline mode (JFB_OFFLINE=1): {repo} is not in the local cache."
                    ) from error
            last = None
            for _ in range(DOWNLOAD_ATTEMPTS):
                try:
                    return TimestralForecaster.from_pretrained(repo, device="cpu")
                except Exception as error:  # network errors come in many types
                    last = error
                    time.sleep(3)
        raise ModelUnavailable(
            f"Could not download {repo} after {DOWNLOAD_ATTEMPTS} attempts: {last}"
        )
