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
