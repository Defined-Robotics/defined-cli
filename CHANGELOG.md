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

### Added
- `manifest.py` — `defined.yaml` project manifest schema and loading with explicit path (no walk-up discovery)
- `ManifestNotFoundError` and `ManifestValidationError` for structured error handling on malformed manifests
- `state/world_loader.py` — `world.yaml` loader with POI/zone/sim models and blackboard seeding
- `launcher.py` — session startup logic extracted from `main.py` (manifest loading, world loading, target selection, session creation)
- `target/docker_image.py` — `DockerImageTarget` for pre-built Docker images via docker-py SDK with host bind mount for BT XML
- `--manifest` CLI flag for explicit `defined.yaml` path
- `Blackboard.clear()` and `Blackboard.clear_pois()` methods
- `docker>=7.0` dependency for Docker SDK integration
- `verbs_dir` threaded from manifest through `DefinedApp` into `DefinedSession.run_mission`

### Changed
- `main.py` modularized — startup logic moved to `launcher.py`, CLI definitions remain
- Target selection logic moved from `main.py._select_target()` to `launcher.select_target()`
- World loading is a soft error — sim can start without a world file, warning shown to user
