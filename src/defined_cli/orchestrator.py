"""Orchestrator — wires target, transport, compiler, and display into a pipeline."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from pathlib import Path

from defined_cli.compiler import CompileResult
from defined_cli.display import DisplayBase
from defined_cli.errors import TaskExecutionError, TransportConnectionError
from defined_cli.target import TargetBase
from defined_cli.transport import TaskProgress, TransportBase

_DEFAULT_TIMEOUT = 300  # seconds
_CONNECT_RETRIES = 30  # rosbridge may take 60s+ after docker compose up
_CONNECT_DELAY = 3  # seconds between retries


class Orchestrator:
    """Runs the full CLI pipeline: start → connect → compile → deploy → monitor."""

    def __init__(
        self,
        target: TargetBase,
        transport: TransportBase,
        display: DisplayBase,
        compile_fn: Callable[[Path, Path, Path | None, Path | None], CompileResult],
    ) -> None:
        self._target = target
        self._transport = transport
        self._display = display
        self._compile_fn = compile_fn
        self._done_event = threading.Event()
        self._first_status = threading.Event()
        self._final_status: TaskProgress | None = None

    def run(
        self,
        task_yaml: Path,
        rdf_yaml: Path,
        verbs_dir: Path | None = None,
        skip_launch: bool = False,
        relaunch: bool = False,
        timeout: float = _DEFAULT_TIMEOUT,
    ) -> None:
        """Execute the full pipeline."""
        try:
            # Phase 1: Start
            if relaunch:
                self._display.show_phase("Relaunching", "tearing down and rebuilding backend")
                self._display.show_log("Force relaunch requested")
                self._target.stop()
                self._target.start()
            elif not skip_launch:
                self._display.show_phase("Starting", "simulation backend")
                self._target.start()

            # Phase 2: Connect (with retries)
            self._display.show_phase("Connecting", "to rosbridge")
            self._connect_with_retries()
            self._display.show_log("Connected to rosbridge")

            # Phase 2b: Readiness check (non-fatal)
            self._display.show_phase("Waiting", "for Nav2 to be ready (up to 30s)")
            if not self._transport.wait_ready(timeout=30.0):
                self._display.show_phase("Warning", "Nav2 not confirmed ready, continuing")
            else:
                self._display.show_log("Nav2 action server ready")

            # Phase 3: Compile
            self._display.show_phase("Compiling", str(task_yaml.name))
            result = self._compile_fn(task_yaml, rdf_yaml, verbs_dir, None)
            self._display.show_log(f"Compiled {len(result.steps)} steps from {task_yaml.name}")

            # Inform display of step list
            self._display.set_steps(result.steps)

            # Phase 4: Wait for BT executor to be ready
            self._display.show_phase("Waiting", "for BT executor (IDLE heartbeat)")
            if not self._transport.wait_for_executor(timeout=60.0):
                raise TaskExecutionError(
                    "BT executor did not start",
                    suggestion="Check container logs: docker compose logs",
                )
            self._display.show_log("BT executor ready")

            # Phase 5: Deploy — subscribe to status first, then send exactly once
            self._display.show_phase("Deploying", "behavior tree")
            resolved = self._target.resolve_xml_path(result.xml_path)

            self._done_event.clear()
            self._final_status = None
            self._first_status = threading.Event()
            self._transport.subscribe_status(self._on_progress)
            self._transport.send_task(resolved)
            self._display.show_log("Sent /task_command")

            # Phase 6: Monitor
            self._display.show_phase("Monitoring", "task execution")

            if not self._done_event.wait(timeout=timeout):
                raise TaskExecutionError(
                    "Task timed out",
                    suggestion=f"No completion signal received within {timeout}s",
                )

            if self._final_status and self._final_status.status == "FAILURE":
                raise TaskExecutionError(
                    f"Task failed at step '{self._final_status.step}'",
                    suggestion="Check robot logs for details",
                )

            self._display.show_success("Task completed successfully")

        finally:
            self._transport.disconnect()

    def _connect_with_retries(self) -> None:
        last_error: TransportConnectionError | None = None
        for attempt in range(_CONNECT_RETRIES):
            try:
                self._transport.connect()
                return
            except TransportConnectionError as exc:
                last_error = exc
                if attempt < _CONNECT_RETRIES - 1:
                    self._display.show_phase(
                        "Connecting",
                        f"retry {attempt + 1}/{_CONNECT_RETRIES}, waiting {_CONNECT_DELAY}s...",
                    )
                    time.sleep(_CONNECT_DELAY)
        raise last_error  # type: ignore[misc]

    def _on_progress(self, progress: TaskProgress) -> None:
        self._first_status.set()  # executor acknowledged the task
        self._display.show_progress(progress)
        if progress.status in ("SUCCESS", "FAILURE"):
            self._final_status = progress
            self._done_event.set()
