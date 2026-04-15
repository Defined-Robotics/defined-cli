"""DefinedSession — unified Python API for all robot interaction.

Single entry point that replaces both Orchestrator (one-shot) and
MissionController (persistent). Manages connection lifecycle, mission
execution, state persistence, and event notification.

This module has zero imports from click, rich, or textual.

Flow
----
``connect()``
    DISCONNECTED → CONNECTING → CONNECTED (starts reconnect watchdog)

``run_mission(task, rdf)``
    Sets COMPILING immediately (under lock), then spawns a daemon thread:
      COMPILING → resolve POI references → compile YAML → BT XML
      DEPLOYING → wait for executor IDLE heartbeat → deploy XML
      RUNNING   → monitor /task_status until SUCCESS/FAILURE/timeout
      SUCCEEDED / FAILED (saved to StateStore)

``stop_mission()``
    Signals the daemon thread to abort; transition → FAILED.

``disconnect()``
    Stops the watchdog, closes transport, sets DISCONNECTED.

Usage (script):
    session = DefinedSession(target=SimTarget(), transport=RosbridgeTransport(),
                             store=StateStore(), compile_fn=compile_task)
    session.connect()
    session.add_poi("dock", 0.0, 0.0)
    session.run_mission(Path("patrol.task.yaml"), Path("robot.rdf.yaml"))
    session.disconnect()

Usage (TUI):
    app = DefinedApp(session)
    app.run()
"""

from __future__ import annotations

import logging
import tempfile
import threading
import time
from collections import deque
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

_log = logging.getLogger(__name__)

from defined_cli.mission.events import ConnectionStatus, MissionStatus, SessionEvent
from defined_cli.transport.readiness import ReadinessReport, build_topic_checks
from defined_cli.mission.resolver import ResolverError, resolve_references
from defined_cli.state.blackboard import Blackboard
from defined_cli.state.model import MissionRecord, RobotStatus, StateSnapshot
from defined_cli.state.store import StateStore
from defined_cli.transport import ExecutorAborted, TaskProgress, TransportBase

if TYPE_CHECKING:
    from defined_cli.compiler import CompileResult, StepInfo
    from defined_cli.target import TargetBase


_RECONNECT_INTERVAL = 2.0
_RECONNECT_MAX_BACKOFF = 30.0
_DEFAULT_TIMEOUT = 300.0
_EXECUTOR_WAIT_TIMEOUT = 60.0
_CONNECT_RETRIES = 30
_CONNECT_DELAY = 3.0


class DefinedSession:
    """Unified Python API for robot interaction.

    Manages the full lifecycle: connection, mission execution, state
    persistence, and event notification. Thread-safe.

    Args:
        target: Backend lifecycle manager (SimTarget, HwTarget).
        transport: Communication layer (RosbridgeTransport).
        store: State persistence (StateStore).
        compile_fn: Task compiler function (compile_task).
    """

    def __init__(
        self,
        target: TargetBase,
        transport: TransportBase,
        store: StateStore,
        compile_fn: Callable[..., CompileResult],
        output_dir: Path | None = None,
    ) -> None:
        self._target = target
        self._transport = transport
        self._store = store
        self._compile_fn = compile_fn
        self._output_dir = output_dir

        self._lock = threading.Lock()
        self._done_event = threading.Event()
        self._stop_event = threading.Event()
        self._listeners: list[Callable[[SessionEvent], None]] = []
        self._snapshot: StateSnapshot = store.load()
        self._reports: deque[str] = deque(maxlen=100)

        self._connection_status = ConnectionStatus.DISCONNECTED
        self._mission_status = MissionStatus.IDLE
        self._step_progress: TaskProgress | None = None
        self._steps: list[StepInfo] = []
        self._current_mission: MissionRecord | None = None
        self._last_error: str | None = None
        self._last_task: Path | None = None
        self._last_rdf: Path | None = None
        self._last_verbs_dir: Path | None = None
        self._last_param_overrides: dict | None = None

        self._latest_readiness: ReadinessReport | None = None
        self._health_thread: threading.Thread | None = None
        self._health_stop = threading.Event()
        self._last_health_ready: bool | None = None

        self._watchdog_thread: threading.Thread | None = None
        self._watchdog_stop = threading.Event()

    # ------------------------------------------------------------------
    # Events
    # ------------------------------------------------------------------

    def add_listener(self, callback: Callable[[SessionEvent], None]) -> None:
        """Register an event listener. Thread-safe."""
        with self._lock:
            self._listeners.append(callback)

    def remove_listener(self, callback: Callable[[SessionEvent], None]) -> None:
        """Unregister an event listener. Thread-safe."""
        with self._lock:
            self._listeners = [cb for cb in self._listeners if cb != callback]

    def _emit(
        self,
        category: str,
        message: str,
        suggestion: str | None = None,
        detail: dict[str, Any] | None = None,
    ) -> None:
        """Create and dispatch a SessionEvent to all listeners."""
        event = SessionEvent(
            timestamp=datetime.now(timezone.utc),
            category=category,  # type: ignore[arg-type]
            message=message,
            suggestion=suggestion,
            detail=detail,
        )
        with self._lock:
            listeners = list(self._listeners)
        for cb in listeners:
            try:
                cb(event)
            except Exception:
                _log.warning("Listener %s raised an exception", cb, exc_info=True)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def connect(self) -> None:
        """Start target (if needed), connect transport, start watchdog."""
        with self._lock:
            self._connection_status = ConnectionStatus.CONNECTING
        self._emit("connection", "Connecting...")

        if self._target.requires_launch:
            self._emit("connection", "Starting backend...")
            self._target.start()

        self._connect_with_retries()

        self._transport.subscribe_reports(self._on_report)
        with self._lock:
            self._connection_status = ConnectionStatus.CONNECTED

        with self._lock:
            self._snapshot.robot.current = RobotStatus.IDLE
            self._store.save(self._snapshot)

        self._emit("connection", "Connected")
        self._start_watchdog()
        self._start_health_monitor()

    def disconnect(self) -> None:
        """Stop watchdog, disconnect transport, update state."""
        self._stop_health_monitor()
        self._stop_watchdog()
        try:
            self._transport.disconnect()
        except Exception:
            _log.debug("Transport disconnect raised an exception", exc_info=True)
        with self._lock:
            self._connection_status = ConnectionStatus.DISCONNECTED

        with self._lock:
            self._snapshot.robot.current = RobotStatus.OFFLINE
            self._store.save(self._snapshot)

        self._emit("connection", "Disconnected")

    def _connect_with_retries(self) -> None:
        """Connect transport with retries (ported from Orchestrator)."""
        from defined_cli.errors import TransportConnectionError

        last_error: TransportConnectionError | None = None
        for attempt in range(_CONNECT_RETRIES):
            try:
                self._transport.connect()
                return
            except TransportConnectionError as exc:
                last_error = exc
                if attempt < _CONNECT_RETRIES - 1:
                    self._emit(
                        "connection",
                        f"Retry {attempt + 1}/{_CONNECT_RETRIES}...",
                        suggestion=f"Waiting {_CONNECT_DELAY}s before next attempt",
                    )
                    time.sleep(_CONNECT_DELAY)
        raise last_error  # type: ignore[misc]

    # ------------------------------------------------------------------
    # Reconnect watchdog
    # ------------------------------------------------------------------

    def _start_watchdog(self) -> None:
        """Start background reconnect watchdog."""
        self._watchdog_stop.clear()
        self._watchdog_thread = threading.Thread(
            target=self._watchdog_loop, daemon=True,
        )
        self._watchdog_thread.start()

    def _stop_watchdog(self) -> None:
        """Stop the reconnect watchdog."""
        self._watchdog_stop.set()
        if self._watchdog_thread is not None:
            self._watchdog_thread.join(timeout=5.0)
            self._watchdog_thread = None

    def _watchdog_loop(self) -> None:
        """Background loop: check connection, reconnect if dropped."""
        backoff = _RECONNECT_INTERVAL
        while not self._watchdog_stop.is_set():
            self._watchdog_stop.wait(timeout=backoff)
            if self._watchdog_stop.is_set():
                break
            if not self._transport.is_connected:
                with self._lock:
                    self._connection_status = ConnectionStatus.RECONNECTING
                self._emit("connection", "Connection lost, reconnecting...")
                try:
                    self._transport.connect()
                    with self._lock:
                        self._connection_status = ConnectionStatus.CONNECTED
                    self._emit("connection", "Reconnected")
                    backoff = _RECONNECT_INTERVAL
                except Exception:
                    backoff = min(backoff * 2, _RECONNECT_MAX_BACKOFF)
                    self._emit(
                        "connection",
                        f"Reconnect failed, retrying in {backoff:.0f}s",
                    )

    # ------------------------------------------------------------------
    # Health monitor
    # ------------------------------------------------------------------

    def _start_health_monitor(self) -> None:
        """Start background health check loop (10s interval)."""
        self._health_stop.clear()
        self._health_thread = threading.Thread(
            target=self._health_loop, daemon=True,
        )
        self._health_thread.start()

    def _stop_health_monitor(self) -> None:
        """Stop the health monitor."""
        self._health_stop.set()
        if self._health_thread is not None:
            self._health_thread.join(timeout=15.0)
            self._health_thread = None

    def _health_loop(self) -> None:
        """Background loop: run readiness check every 10s."""
        checks = build_topic_checks()
        while not self._health_stop.is_set():
            try:
                report = self._transport.check_readiness(checks)
                with self._lock:
                    self._latest_readiness = report
                current_ready = report.ready
                if current_ready != self._last_health_ready:
                    self._last_health_ready = current_ready
                    self._emit(
                        "health",
                        report.summary(),
                        detail={"ready": current_ready, "failed": [r.topic for r in report.failed]},
                    )
            except Exception:
                _log.debug("Health check failed", exc_info=True)
            self._health_stop.wait(timeout=10.0)

    # ------------------------------------------------------------------
    # Compile (standalone, no transport needed)
    # ------------------------------------------------------------------

    def compile(
        self,
        task: Path,
        rdf: Path,
        *,
        verbs_dir: Path | None = None,
    ) -> CompileResult:
        """Compile a task YAML to BT XML. Works without connection."""
        return self._compile_fn(task, rdf, verbs_dir, self._output_dir)

    # ------------------------------------------------------------------
    # Mission execution
    # ------------------------------------------------------------------

    def run_mission(
        self,
        task: Path,
        rdf: Path,
        *,
        verbs_dir: Path | None = None,
        timeout: float = _DEFAULT_TIMEOUT,
        param_overrides: dict | None = None,
    ) -> None:
        """Compile, deploy, and monitor a mission. Non-blocking.

        Spawns a daemon thread. Use ``mission_status`` property to
        track progress. Events are emitted to listeners.

        Args:
            param_overrides: Key/value pairs that override matching params in
                every task step at compile time. E.g. ``{"timeout": "120"}``
                overrides the ``timeout`` param on any step that declares it.
        """
        with self._lock:
            if self._mission_status in (
                MissionStatus.COMPILING,
                MissionStatus.DEPLOYING,
                MissionStatus.RUNNING,
            ):
                raise RuntimeError("A mission is already running. Use stop_mission() first.")
            # Mark as COMPILING before releasing the lock so that a
            # concurrent call cannot also pass the guard above.
            self._mission_status = MissionStatus.COMPILING
            self._last_task = task
            self._last_rdf = rdf
            self._last_verbs_dir = verbs_dir
            self._last_param_overrides = param_overrides

        thread = threading.Thread(
            target=self._run_mission_thread,
            args=(task, rdf, verbs_dir, timeout, param_overrides),
            daemon=True,
        )
        thread.start()

    def stop_mission(self) -> None:
        """Stop the current mission gracefully. No-op if nothing running."""
        with self._lock:
            was_running = self._mission_status in (
                MissionStatus.COMPILING,
                MissionStatus.DEPLOYING,
                MissionStatus.RUNNING,
            )
        if not was_running:
            return

        # Cancel the BT executor (halts running nodes, cancels Nav2 goals)
        self._transport.cancel_task()
        # Zero velocity so the robot stops moving
        self._transport.publish_velocity(0.0, 0.0)
        # Signal mission thread to exit
        self._stop_event.set()
        self._done_event.set()

        self._emit("mission", "Mission stopped by user")

    def restart_mission(self) -> None:
        """Re-run the last mission with the same arguments."""
        with self._lock:
            task = self._last_task
            rdf = self._last_rdf
            verbs_dir = self._last_verbs_dir
            param_overrides = self._last_param_overrides
        if task is None or rdf is None:
            msg = "No previous mission to restart"
            raise RuntimeError(msg)
        self.run_mission(task, rdf, verbs_dir=verbs_dir, param_overrides=param_overrides)

    def _resolve_task(
        self,
        task_yaml: Path,
        rdf_yaml: Path,
        verbs_dir: Path | None,
        param_overrides: dict | None,
    ) -> CompileResult:
        """Resolve POI references and compile task YAML to BT XML.

        If the task contains ``$world.pois.*`` references, writes a
        resolved copy to a temp file, compiles it, then cleans up.

        Args:
            task_yaml: Path to the task YAML file.
            rdf_yaml: Path to the robot RDF YAML file.
            verbs_dir: Optional directory of verb templates.
            param_overrides: Optional key/value compile-time overrides.

        Returns:
            CompileResult with the generated XML path and step list.

        Raises:
            ResolverError: If a POI reference cannot be resolved.
        """
        task_dict = yaml.safe_load(task_yaml.read_text())
        with self._lock:
            pois = dict(self._snapshot.world.pois)
        bb = Blackboard(data={"world": {"pois": pois}})
        resolved_dict = resolve_references(task_dict, bb)

        if resolved_dict != task_dict:
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".yaml", dir=task_yaml.parent,
                delete=False, prefix=f".{task_yaml.stem}_resolved_",
            ) as tmp:
                yaml.dump(resolved_dict, tmp)
                resolved_path = Path(tmp.name)
            try:
                return self._compile_fn(
                    resolved_path, rdf_yaml, verbs_dir, self._output_dir,
                    param_overrides=param_overrides,
                )
            finally:
                resolved_path.unlink(missing_ok=True)

        return self._compile_fn(
            task_yaml, rdf_yaml, verbs_dir, self._output_dir,
            param_overrides=param_overrides,
        )

    def _begin_mission(self, record: MissionRecord, mission_id: str) -> None:
        """Initialize mission state. Must be called with ``_lock`` held."""
        self._current_mission = record
        self._mission_status = MissionStatus.COMPILING
        self._step_progress = None
        self._last_error = None
        self._snapshot.robot.current = RobotStatus.ON_MISSION
        self._snapshot.robot.last_mission_id = mission_id
        self._store.save(self._snapshot)

    def _finalize_mission(self, record: MissionRecord, outcome: str) -> None:
        """Persist final mission state. Must be called with ``_lock`` held."""
        record.status = outcome
        record.completed_at = datetime.now(timezone.utc).isoformat()
        record.result = outcome
        self._snapshot.mission_history.append(record)

        # Only update live status if this mission is still the active one.
        # After E-STOP a new mission may have already started; the old thread
        # must not overwrite COMPILING/DEPLOYING/RUNNING with FAILED.
        if self._current_mission is record:
            self._snapshot.robot.current = RobotStatus.IDLE
            self._snapshot.robot.last_mission_result = outcome
            self._current_mission = record
            self._mission_status = (
                MissionStatus.SUCCEEDED if outcome == "SUCCESS"
                else MissionStatus.FAILED
            )
        self._store.save(self._snapshot)

    def _run_mission_thread(
        self,
        task_yaml: Path,
        rdf_yaml: Path,
        verbs_dir: Path | None,
        timeout: float,
        param_overrides: dict | None = None,
    ) -> None:
        """Mission worker — runs in a daemon thread."""
        self._stop_event.clear()
        self._done_event.clear()

        ts = datetime.now(timezone.utc).strftime("%H%M%S")
        task_base = task_yaml.name.split(".")[0]
        mission_id = f"{task_base}-{ts}"

        record = MissionRecord(
            id=mission_id,
            task_name=task_base,
            status="RUNNING",
            started_at=datetime.now(timezone.utc).isoformat(),
        )

        with self._lock:
            self._begin_mission(record, mission_id)

        self._emit("mission", f"Mission {mission_id} started")

        outcome = "FAILURE"
        try:
            # Compile phase
            self._emit("mission", f"Compiling {task_yaml.name}...")
            result = self._resolve_task(task_yaml, rdf_yaml, verbs_dir, param_overrides)

            with self._lock:
                self._steps = list(result.steps)
                self._mission_status = MissionStatus.DEPLOYING

            self._emit(
                "mission",
                f"Compiled {len(result.steps)} steps",
                detail={"steps": [s.label for s in result.steps]},
            )

            # Pre-mission health warning
            with self._lock:
                readiness = self._latest_readiness
            if readiness is not None and not readiness.ready:
                failed_topics = ", ".join(r.topic for r in readiness.failed)
                self._emit(
                    "health",
                    f"Warning: topics not publishing: {failed_topics}",
                    suggestion="Some subsystems may be down. Mission will proceed.",
                )

            if self._stop_event.is_set():
                outcome = "ABORTED"
                return

            # Deploy phase
            self._emit("mission", "Waiting for executor...")
            try:
                executor_ready = self._transport.wait_for_executor(
                    timeout=_EXECUTOR_WAIT_TIMEOUT,
                    abort_event=self._stop_event,
                )
            except ExecutorAborted:
                outcome = "ABORTED"
                return
            if not executor_ready:
                raise TimeoutError(
                    f"BT executor did not become ready within {_EXECUTOR_WAIT_TIMEOUT}s"
                )

            if self._stop_event.is_set():
                outcome = "ABORTED"
                return

            xml_path_str = self._target.resolve_xml_path(result.xml_path)

            self._transport.subscribe_status(self._on_progress)
            self._transport.send_task(xml_path_str)

            with self._lock:
                self._mission_status = MissionStatus.RUNNING

            self._emit("mission", "Deployed, monitoring execution...")

            # Monitor phase
            self._done_event.wait(timeout=timeout)

            if self._stop_event.is_set():
                outcome = "ABORTED"
                return

            final = self._step_progress
            if final and final.status == "SUCCESS":
                outcome = "SUCCESS"
            elif not self._done_event.is_set():
                outcome = "TIMEOUT"
                self._emit(
                    "error",
                    f"Mission timed out after {timeout}s",
                    suggestion="Increase timeout or check if robot is stuck",
                )
            else:
                outcome = "FAILURE"

        except ResolverError as exc:
            with self._lock:
                self._last_error = str(exc)
            self._emit(
                "error",
                f"POI resolution failed: {exc}",
                suggestion="Check POI names with /world list",
            )
        except Exception as exc:
            _log.exception("Unexpected error in mission thread")
            with self._lock:
                self._last_error = str(exc)
            self._emit(
                "error",
                f"Mission failed: {exc}",
                detail={"exception": type(exc).__name__, "message": str(exc)},
            )
        finally:
            with self._lock:
                self._finalize_mission(record, outcome)

            self._emit("mission", f"Mission {outcome.lower()}: {mission_id}")

    def _on_progress(self, progress: TaskProgress) -> None:
        """Handle TaskProgress from transport. Called from Twisted thread."""
        with self._lock:
            if progress.status == "IDLE":
                return
            self._step_progress = progress
        if progress.status in ("SUCCESS", "FAILURE"):
            self._done_event.set()
        self._emit(
            "executor",
            f"Step {progress.current}/{progress.total}: {progress.step} ({progress.status})",
            detail={
                "step": progress.step,
                "status": progress.status,
                "current": progress.current,
                "total": progress.total,
                "progress": progress.progress,
            },
        )

    def _on_report(self, message: str) -> None:
        """Handle report from /task_reports."""
        with self._lock:
            self._reports.append(message)
        self._emit("mission", f"Report: {message}")

    # ------------------------------------------------------------------
    # World management
    # ------------------------------------------------------------------

    def add_poi(
        self,
        name: str,
        x: float,
        y: float,
        *,
        poi_type: str = "static",
        radius: float = 0.5,
    ) -> None:
        """Add or update a Point of Interest."""
        with self._lock:
            bb = Blackboard(data={"world": {"pois": self._snapshot.world.pois}})
            bb.set_poi(name, (x, y), radius=radius, poi_type=poi_type)
            self._snapshot.world.pois = bb.list_pois()
            self._store.save(self._snapshot)

    def list_pois(self) -> dict[str, dict]:
        """Return all POIs as a dict."""
        with self._lock:
            return dict(self._snapshot.world.pois)

    def mark_poi(self, name: str, *, poi_type: str = "static", radius: float = 0.5) -> tuple[float, float]:
        """Mark the robot's current position as a named POI."""
        x, y = self._transport.fetch_pose()
        self.add_poi(name, x, y, poi_type=poi_type, radius=radius)
        return (x, y)

    # ------------------------------------------------------------------
    # Read-only properties (all thread-safe)
    # ------------------------------------------------------------------

    @property
    def latest_readiness(self) -> ReadinessReport | None:
        """Most recent readiness check result."""
        with self._lock:
            return self._latest_readiness

    @property
    def connection_status(self) -> ConnectionStatus:
        """Current transport connection state."""
        with self._lock:
            return self._connection_status

    @property
    def mission_status(self) -> MissionStatus:
        """Current mission execution state."""
        with self._lock:
            return self._mission_status

    @property
    def state(self) -> StateSnapshot:
        """Current state snapshot (read-only copy)."""
        with self._lock:
            return StateSnapshot.from_dict(self._snapshot.to_dict())

    @property
    def blackboard(self) -> Blackboard:
        """Blackboard with current world state."""
        with self._lock:
            return Blackboard(data={"world": {"pois": dict(self._snapshot.world.pois)}})

    @property
    def current_progress(self) -> TaskProgress | None:
        """Latest TaskProgress update, or None if idle."""
        with self._lock:
            return self._step_progress

    @property
    def last_mission(self) -> MissionRecord | None:
        """Most recently completed or active mission record."""
        with self._lock:
            return self._current_mission

    @property
    def steps(self) -> list[StepInfo]:
        """Steps from the most recently compiled mission."""
        with self._lock:
            return list(self._steps)

    @property
    def reports(self) -> list[str]:
        """Recent report messages."""
        with self._lock:
            return list(self._reports)

    def publish_velocity(self, linear_x: float, angular_z: float) -> None:
        """Publish a velocity command to /cmd_vel. No-op if not connected."""
        self._transport.publish_velocity(linear_x, angular_z)

    def emergency_stop(self) -> None:
        """Immediately halt all motion and abort any running mission.

        Publishes zero velocity to /cmd_vel, signals the mission thread to
        stop, and marks the mission as FAILED. Safe to call from any state.
        """
        # Halt the BT executor first — triggers onHalted() on all running nodes,
        # which cancels Nav2 goals and stops explore_lite via resume=false.
        # Must come before zero-velocity so the navigation stack stops issuing
        # new /cmd_vel commands that would override our stop.
        self._transport.cancel_task()

        # Send zero-velocity as belt-and-suspenders while Nav2 processes the cancel
        self._transport.publish_velocity(0.0, 0.0)

        # Signal the mission thread to abort
        self._stop_event.set()
        self._done_event.set()

        with self._lock:
            if self._mission_status in (
                MissionStatus.COMPILING,
                MissionStatus.DEPLOYING,
                MissionStatus.RUNNING,
            ):
                self._mission_status = MissionStatus.FAILED

        self._emit(
            "mission",
            "Emergency stop activated",
            suggestion="Verify robot is stationary before resuming",
        )

    @property
    def last_error(self) -> str | None:
        """Error from the most recent failed mission."""
        with self._lock:
            return self._last_error
