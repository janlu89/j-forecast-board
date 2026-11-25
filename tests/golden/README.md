# Golden tests

These tests pin the JSON that the current app returns, so that refactoring cannot change a number
without someone noticing. They start the app in-process against **copies** of the fixtures in a
temporary folder (`JFB_HOME`), never against a real install.

| Group | Needs the model | Tolerance | Run |
|---|---|---|---|
| `test_cached_views.py`, `test_access.py` | no (cached backtests) | `rel=1e-6` | `pytest -m "not model"` |
| `test_model_views.py` (`@pytest.mark.model`) | Timestral-28M in the local Hugging Face cache | `rel=1e-3` | `pytest -m model` |

The model group never downloads weights (`HF_HUB_OFFLINE=1`) and is skipped when they are missing.
It is not meant for CI.

## Updating a snapshot on purpose

Only when a behaviour change is intended:

```
JFB_UPDATE_GOLDEN=1 pytest tests/golden
git diff tests/golden/snapshots
```

Review the diff, then commit it together with the change that caused it.

## The synthetic panel

`conftest.py` builds a made-up dataset of three daily series (`synthetic`) with a deterministic fake
backtest result, to cover the views that only exist for panels: totals, distributions, best and
worst series, breakdown by attribute.

## Fixture sources

Only small public datasets are committed. The Rossmann data is Kaggle competition data and must
never be added here.

| File | Content | Source and licence |
|---|---|---|
| `fixtures/data/airline-passengers.csv` | international airline passengers per month, 1949-1960 | Box, G. E. P. and Jenkins, G. M. (1976), *Time Series Analysis: Forecasting and Control*; file from the public repository `jbrownlee/Datasets` on GitHub. A classic textbook series, widely redistributed. |
| `fixtures/data/bike_sharing.zip` | Capital Bikeshare rentals, 2011-2012 (the original archive, with its `Readme.txt`) | UCI Machine Learning Repository, dataset 275, licence CC BY 4.0. Cite: Fanaee-T, H. and Gama, J. (2013), "Event labeling combining ensemble detectors and background knowledge", *Progress in Artificial Intelligence*, doi:10.1007/s13748-013-0040-3. |
| `fixtures/results/passengers/*.npz`, `fixtures/results/bike/*.npz` | cached backtests of Timestral-28M on the two datasets above | produced by this app on 2026-11-02 |

The snapshots in `snapshots/` were captured from the app on 2026-11-25 and checked against the
original demo, still running unmodified at the time: the responses for `passengers` and `bike`
were identical.
