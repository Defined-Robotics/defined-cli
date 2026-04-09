"""Transport protocol — how the CLI talks to a running backend.

A transport handles pub/sub communication between the CLI (host)
and the platform backend (Docker container, remote hardware, etc.).

The default implementation is ``RosbridgeTransport`` which connects
via WebSocket to rosbridge at ``ws://localhost:9090``.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass


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

        Default implementation is a no-op (backwards compat).
        """

    def wait_for_executor(self, timeout: float = 60.0) -> bool:
        """Wait for the BT executor to publish an IDLE heartbeat.

        Returns True when the executor is ready, False on timeout.
        Default implementation returns True immediately (backwards compat).
        """
        return True

    def publish_velocity(self, linear_x: float, angular_z: float) -> None:
        """Publish a velocity command to /cmd_vel.

        Default is a no-op for backends that don't support velocity control.
        """

    @property
    def is_connected(self) -> bool:
        """True if currently connected. Subclasses should override."""
        return False
