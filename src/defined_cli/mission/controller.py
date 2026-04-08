"""MissionController — persistent mission control loop.

Connects the transport once, holds StateStore + Blackboard in memory,
and runs missions (compile → deploy → monitor) in a daemon thread.
State transitions are written atomically to ~/.defined/state.yaml on
every change.

This module has zero imports from click, rich, or textual so it can
be extracted to ``defined-core`` in Milestone 2 without modification.

Usage:
    from defined_cli.mission.controller import MissionController
    from defined_cli.state.store import StateStore
    from defined_cli.transport.rosbridge import RosbridgeTransport

    store = StateStore()
    transport = RosbridgeTransport()
    controller = MissionController(store=store, transport=transport, compile_fn=compile_task)
    controller.connect()
    controller.launch_mission(Path("patrol.task.yaml"), Path("robot.rdf.yaml"))
"""

from __future__ import annotations

import tempfile
import threading
import time
from collections import deque
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

import yaml

from defined_cli.errors import TransportConnectionError
from defined_cli.mission.resolver import ResolverError, resolve_references
from defined_cli.state.blackboard import Blackboard
from defined_cli.state.model import MissionRecord, RobotStatus, StateSnapshot
from defined_cli.state.store import StateStore
from defined_cli.transport import TaskProgress, TransportBase

if TYPE_CHECKING:
    from defined_cli.compiler import CompileResult, StepInfo
    from defined_cli.target import TargetBase


class MissionController:
    """Persistent mission control: connect once, run many missions.

    Owns the StateStore (single writer) and keeps an in-memory snapshot
    synced with ``~/.defined/state.yaml``. Transport is connected at
    ``connect()`` and disconnected at ``disconnect()`` — the lifetime
    of both is controlled by the caller (MonitorDisplay).

    Args:
        store: StateStore for reading/writing ``~/.defined/state.yaml``.
        transport: Transport implementation (rosbridge, mock, etc.).
        compile_fn: Function with the same signature as ``compile_task``.
        target: Optional target for resolving BT XML paths (SimTarget).
            If None, the xml_path from compile_fn is used as-is.
    """

    def __init__(
        self,
        store: StateStore,
        transport: TransportBase,
        compile_fn: Callable[..., CompileResult],
        target: TargetBase | None = None,
    ) -> None:
        self._lock = threading.Lock()
        self._done_event = threading.Event()
        self._store = store
        self._transport = transport
        self._compile_fn = compile_fn
        self._target = target
        self._snapshot: StateSnapshot = store.load()
        self._reports: deque[str] = deque(maxlen=100)
        self._steps: list[StepInfo] = []
        self._step_progress: TaskProgress | None = None
        self._current_mission: MissionRecord | None = None
        self._last_error: str | None = None
        self._mission_running = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def connect(self) -> None:
        """Connect the transport and transition robot to IDLE."""
        self._transport.connect()
        self._transport.subscribe_reports(self._on_report)
        with self._lock:
            self._snapshot.robot.current = RobotStatus.IDLE
            self._store.save(self._snapshot)

    def disconnect(self) -> None:
        """Disconnect the transport and transition robot to OFFLINE."""
        self._transport.disconnect()
        with self._lock:
            self._snapshot.robot.current = RobotStatus.OFFLINE
            self._store.save(self._snapshot)

    def reconnect(self, max_retries: int = 5, delay: float = 3.0) -> bool:
        """Attempt to reconnect after a connection drop.

        Disconnects first (safe even if already disconnected), then
        retries ``connect()`` up to ``max_retries`` times.

        Args:
            max_retries: Number of attempts before giving up.
            delay: Seconds to wait between attempts.

        Returns:
            True if reconnected successfully, False after exhausting retries.
        """
        try:
            self._transport.disconnect()
        except Exception:
            pass

        for attempt in range(max_retries):
            try:
                self._transport.connect()
                with self._lock:
                    self._snapshot.robot.current = RobotStatus.IDLE
                    self._store.save(self._snapshot)
                return True
            except TransportConnectionError:
                if attempt < max_retries - 1:
                    time.sleep(delay)
        return False

    # ------------------------------------------------------------------
    # Mission launch
    # ------------------------------------------------------------------

    def launch_mission(
        self,
        task_yaml: Path,
        rdf_yaml: Path,
        verbs_dir: Path | None = None,
        timeout: float = 300.0,
    ) -> None:
        """Queue a mission for execution.

        Spawns a daemon thread to run compile → deploy → monitor.
        Returns immediately. Use ``is_mission_running`` to poll status.

        Args:
            task_yaml: Path to the task YAML file.
            rdf_yaml: Path to the robot RDF YAML file.
            verbs_dir: Optional directory with verb templates.
            timeout: Maximum seconds to wait for task completion.
        """
        thread = threading.Thread(
            target=self._run_mission,
            args=(task_yaml, rdf_yaml, verbs_dir, timeout),
            daemon=True,
        )
        thread.start()

    def _run_mission(
        self,
        task_yaml: Path,
        rdf_yaml: Path,
        verbs_dir: Path | None,
        timeout: float,
    ) -> None:
        """Internal mission runner — executes in a daemon thread."""
        ts = datetime.now(timezone.utc).strftime("%H%M%S")
        # Use the base name without any extensions (e.g. "patrol" from "patrol.task.yaml")
        task_base = task_yaml.name.split(".")[0]
        mission_id = f"{task_base}-{ts}"

        record = MissionRecord(
            id=mission_id,
            task_name=task_base,
            status="RUNNING",
            started_at=datetime.now(timezone.utc).isoformat(),
        )

        with self._lock:
            self._current_mission = record
            self._mission_running = True
            self._snapshot.robot.current = RobotStatus.ON_MISSION
            self._snapshot.robot.last_mission_id = mission_id
            self._store.save(self._snapshot)

        outcome = "FAILURE"
        try:
            # Resolve POI references ($world.pois.X → x/y coords)
            task_dict = yaml.safe_load(task_yaml.read_text())
            with self._lock:
                pois = dict(self._snapshot.world.pois)
            bb = Blackboard(data={"world": {"pois": pois}})
            resolved_dict = resolve_references(task_dict, bb)

            # Write resolved YAML to a temp file only if anything changed
            if resolved_dict != task_dict:
                with tempfile.NamedTemporaryFile(
                    mode="w",
                    suffix=".yaml",
                    dir=task_yaml.parent,
                    delete=False,
                    prefix=f".{task_yaml.stem}_resolved_",
                ) as tmp:
                    yaml.dump(resolved_dict, tmp)
                    resolved_path = Path(tmp.name)
                try:
                    result = self._compile_fn(resolved_path, rdf_yaml, verbs_dir, None)
                finally:
                    resolved_path.unlink(missing_ok=True)
            else:
                result = self._compile_fn(task_yaml, rdf_yaml, verbs_dir, None)

            with self._lock:
                self._steps = list(result.steps)

            # Resolve path for the backend (e.g. Docker volume mapping)
            if self._target is not None:
                xml_path_str = self._target.resolve_xml_path(result.xml_path)
            else:
                xml_path_str = str(result.xml_path)

            self._transport.wait_for_executor(timeout=60.0)
            self._done_event.clear()
            self._transport.subscribe_status(self._on_progress)
            self._transport.send_task(xml_path_str)
            self._done_event.wait(timeout=timeout)

            final = self._step_progress
            if final and final.status == "SUCCESS":
                outcome = "SUCCESS"
            else:
                outcome = "FAILURE"

        except ResolverError as exc:
            with self._lock:
                self._last_error = str(exc)
        except Exception as exc:
            with self._lock:
                self._last_error = str(exc)

        with self._lock:
            record.status = outcome
            record.completed_at = datetime.now(timezone.utc).isoformat()
            record.result = outcome
            self._snapshot.mission_history.append(record)
            self._snapshot.robot.current = RobotStatus.IDLE
            self._snapshot.robot.last_mission_result = outcome
            self._mission_running = False
            self._current_mission = record
            self._store.save(self._snapshot)

    def _on_progress(self, progress: TaskProgress) -> None:
        """Handle a TaskProgress message from the transport.

        Called from the Twisted reactor thread — must be lock-safe.
        """
        with self._lock:
            # Ignore IDLE heartbeats — they reset current/total/progress to 0
            # which would clobber the final SUCCESS/FAILURE snapshot.
            if progress.status == "IDLE":
                return
            self._step_progress = progress

        if progress.status in ("SUCCESS", "FAILURE"):
            self._done_event.set()

    def _on_report(self, message: str) -> None:
        """Handle a report message from /task_reports."""
        with self._lock:
            self._reports.append(message)

    # ------------------------------------------------------------------
    # Read-only state properties (all thread-safe via _lock)
    # ------------------------------------------------------------------

    @property
    def robot_status(self) -> RobotStatus:
        """Current robot state enum."""
        with self._lock:
            return self._snapshot.robot.current

    @property
    def steps(self) -> list[StepInfo]:
        """Steps from the most recently compiled mission."""
        with self._lock:
            return list(self._steps)

    @property
    def step_progress(self) -> TaskProgress | None:
        """Most recent TaskProgress update from the executor."""
        with self._lock:
            return self._step_progress

    @property
    def reports(self) -> list[str]:
        """Recent report-verb messages (bounded deque as list)."""
        with self._lock:
            return list(self._reports)

    @property
    def mission_history(self) -> list[MissionRecord]:
        """All completed missions this session (from state snapshot)."""
        with self._lock:
            return list(self._snapshot.mission_history)

    @property
    def pois(self) -> dict[str, dict]:
        """Current Points of Interest from the world state."""
        with self._lock:
            return dict(self._snapshot.world.pois)

    @property
    def current_mission(self) -> MissionRecord | None:
        """The active or most recently completed MissionRecord."""
        with self._lock:
            return self._current_mission

    @property
    def is_mission_running(self) -> bool:
        """True if a mission is currently executing."""
        with self._lock:
            return self._mission_running

    @property
    def last_error(self) -> str | None:
        """Error string from the most recent failed mission, or None."""
        with self._lock:
            return self._last_error
