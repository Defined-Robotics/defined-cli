# Changelog

All notable changes to `defined-cli` are documented here.

Contributors: add entries under `[Unreleased]` as part of your PR.
Release PRs (`release/vX.Y.Z`) promote `[Unreleased]` → the versioned heading.

---

## [0.0.2] - 2026-04-06

### Changed
- Rename `ConnectionError` → `TransportConnectionError` to avoid shadowing the Python built-in
- Annotate internal error-translator functions with `NoReturn`
- Add `_first_status` Event to `Orchestrator` for executor-ready handshake
- Add CI: `Dockerfile.ci` and GitHub Actions workflow
- Move `textual` to optional `[tui]` extra; keep in `[dev]` for test runs
- Lower `requires-python` to `>=3.9` for broader compatibility

### Added
- Initial package scaffold: `defined-cli` with `compile`, `run`, `stop`, `status` commands
- Error hierarchy: `DefinedError`, `CompilationError`, `TransportConnectionError`, `TaskExecutionError`, `BackendError`
- Protocol ABCs: `TargetBase`, `TransportBase`, `DisplayBase`
- `SimTarget` and `RosbridgeTransport` implementations
- `Orchestrator` pipeline: compile → connect → send → wait → disconnect
- `RichDisplay` for terminal output and `TUI` full-screen Textual app with step tracker, progress bar, elapsed timer
- Nav2 readiness probe (`bt_navigator/transition_event` topic)
- `--tui` / `--timeout` CLI flags
- Race condition fix: CLI waits for executor IDLE heartbeat before sending task command
- 102 passing tests (unit + integration)

---

## [Unreleased]

_No unreleased changes yet._
