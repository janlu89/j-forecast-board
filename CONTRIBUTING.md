# Contributing

Thank you for helping. Small, focused pull requests are easiest to review.

## Set up

```
git clone https://github.com/janlu89/j-forecast-board.git
cd j-forecast-board
python -m venv .venv && . .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
pip install -e ".[dev]"
pre-commit install
```

## Checks (all must pass)

```
ruff format --check . && ruff check .
lint-imports
pytest -m "not model"
node --test "tests/js/*.test.mjs"
```

`pytest -m model` also runs the forecasts with the real Timestral-28M weights (in the Hugging Face
cache); it is not run on CI.

## Rules of the code base

- **Dependencies point inward** (`docs/architecture.md`): domain ← application ← adapters ←
  bootstrap. `lint-imports` enforces it.
- **Clean Code**: names that say what, small functions with one level of abstraction, no flag
  arguments, errors as exceptions mapped to HTTP codes in one place, comments that explain why.
- **Tests first** for new behaviour; one concept per test; names that state the behaviour.
- **The golden snapshots** in `tests/golden/snapshots` pin every number the views return. A change
  to them must be intended: regenerate with `JFB_UPDATE_GOLDEN=1 pytest tests/golden` and explain
  the diff in the pull request.
- **No new dependency** without discussing it first; prefer MIT / BSD / Apache-2.0.
- **Never commit** data that is not public, secrets, or files from a runtime folder.
- Commits follow Conventional Commits (`feat:`, `fix:`, `refactor:`, `test:`, `docs:`, `build:`, `ci:`).

## Licence of contributions

Contributions are accepted under the Apache License 2.0 (inbound = outbound). Sign off your commits
(`git commit -s`) to certify the [Developer Certificate of Origin](https://developercertificate.org/).
