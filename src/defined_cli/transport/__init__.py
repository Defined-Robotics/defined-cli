"""Transport protocol — how the CLI talks to a running backend.

A transport handles pub/sub communication between the CLI (host)
and the platform backend (Docker container, remote hardware, etc.).

The default implementation is ``RosbridgeTransport`` which connects
via WebSocket to rosbridge at ``ws://localhost:9090``.
"""

from __future__ import annotations

import threading
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass


class ExecutorAborted(Exception):
    """Raised by wait_for_executor when cancelled by an abort_event.

    Distinct from TimeoutError so callers can tell an E-STOP abort apart
    from a genuine timeout without re-reading the (now potentially cleared)
    abort_event flag.
    """


@dataclass(frozen=True)
class TaskProgress:
    """Progress update from the BT executor.

    Mirrors the JSON published by task_status_publisher.cpp:
        {"step": "GoTo", "status": "RUNNING", "current": 2, "total": 5, "progress": 40}
    """
    step: str
    status: str
    current: int
    total: int
    progress: int


class TransportBase(ABC):
    """Abstract base for CLI ↔ backend communication."""

    @abstractmethod
    def connect(self) -> None:
        """Establish connection. Raises ConnectionError on failure."""

    @abstractmethod
    def disconnect(self) -> None:
        """Close the connection."""

    @abstractmethod
    def send_task(self, bt_xml_path: str) -> None:
        """Publish a BT XML path to /task_command."""

    @abstractmethod
    def subscribe_status(self, callback: Callable[[TaskProgress], None]) -> None:
        """Subscribe to /task_status and deliver parsed TaskProgress to callback."""

    @abstractmethod
    def wait_ready(self, timeout: float = 10.0) -> bool:
        """Wait for the backend (Nav2) to be ready. Returns False on timeout."""

    def subscribe_reports(self, callback: Callable[[str], None]) -> None:
        """Subscribe to /task_reports and deliver message strings to callback.

        Optional — no-op default so that transports that pre-date report
        subscriptions remain compatible without change.

        Args:
            callback: Called with each report message string.
        """

    def wait_for_executor(
        self,
        timeout: float = 60.0,
        abort_event: threading.Event | None = None,
    ) -> bool:
        """Wait for the BT executor to publish an IDLE heartbeat.

        Returns True when the executor is ready, False on timeout or abort.

        Optional — default returns True immediately (treats the executor
        as always ready). **Override this in real transports.** The
        session treats a False return as a hard error and will not send
        the task, so an incorrect True here silences readiness failures.

        Args:
            timeout:     Seconds to wait before giving up.
            abort_event: Optional event that cancels the wait early (e.g. E-STOP).

        Returns:
            True if the executor became ready within *timeout*, else False.
        """
        return True

    def cancel_task(self) -> None:
        """Send a stop command to the BT executor to halt the running tree.

        Publishes ``"STOP"`` to ``/task_command``, which causes the executor
        to call ``haltTree()`` — triggering ``onHalted()`` on every running
        BT node (cancels Nav2 goals, stops explore_lite, etc.).

        Optional — no-op default for transports that don't support task
        cancellation (e.g. replay or test transports).
        """

    def publish_velocity(self, linear_x: float, angular_z: float) -> None:
        """Publish a velocity command to /cmd_vel.

        Optional — no-op default for transports that don't support
        direct velocity control (e.g. replay or test transports).

        Args:
            linear_x: Forward/backward velocity in m/s.
            angular_z: Rotation velocity in rad/s.
        """

    def fetch_pose(self, timeout: float = 5.0, topic: str = "/odom") -> tuple[float, float]:
        """Fetch the robot's current (x, y) position via the existing connection.

        Optional — raises ``NotImplementedError`` by default. Override in
        transports that support live pose queries.

        Args:
            timeout: Seconds to wait for a pose message.
            topic: ROS2 topic to read (e.g. ``"/odom"`` or ``"/amcl_pose"``).

        Returns:
            ``(x, y)`` position in the map frame.

        Raises:
            NotImplementedError: If this transport does not support pose queries.
            TimeoutError: If no pose is received within *timeout*.
        """
        raise NotImplementedError("fetch_pose not supported by this transport")

    @property
    def is_connected(self) -> bool:
        """True if currently connected. Subclasses should override."""
        return False
