# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow [SemVer](https://semver.org/).

## [0.1.0] - unreleased

First release as a product, grown out of an internal Timestral demo.

### Added
- Setup and start scripts for Windows (`setup.cmd`, `start.cmd`, PowerShell 5.1 and 7) and Linux.
- `python -m j_forecast_board doctor` checks the PC and writes a shareable report.
- Stub model (`JFB_MODEL=stub`) to try the board without downloading weights.
- Settings from `JFB_*` variables, a per-user runtime folder, offline mode, admin policy file.
- AI assistant, off until set up: local model, OpenAI-compatible APIs, Claude Code CLI; consent
  before data leaves the PC; Local / External badge; private datasets never sent outside.
- Terminal setup for the assistant: `python -m j_forecast_board agent …`.
- Audit log, sign-in lock-out, `password` and `purge` commands, security headers and CSP.
- Delete button for uploaded datasets.

### Changed
- Clean Architecture layout; the numbers of every view are unchanged (golden tests).
- The sign-in password is stored as a scrypt hash.
- Errors answer with proper HTTP status codes.

### Fixed
- A cached result cut by a crash no longer stops the next start.
- On datasets without covariates, choosing another model size no longer waits forever.
