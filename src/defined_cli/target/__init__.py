"""Target protocol — how the CLI manages backend lifecycle.

A target handles starting, stopping, and health-checking the
platform backend. It also translates host filesystem paths to
paths the backend can access (e.g., Docker volume mounts).

The default implementation is ``SimTarget`` which manages the
simulation stack via ``docker compose``.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from enum import Enum
from pathlib import Path


class TargetStatus(Enum):
    """Current state of the backend managed by a Target."""
    RUNNING = "running"
    STOPPED = "stopped"
    STARTING = "starting"
    ERROR = "error"


class TargetBase(ABC):
    """Abstract base for backend lifecycle management."""

    @abstractmethod
    def start(self) -> None:
        """Bring up the backend. Raises BackendError on failure."""

    @abstractmethod
    def stop(self) -> None:
        """Tear down the backend."""

    @abstractmethod
    def status(self) -> TargetStatus:
        """Query whether the backend is running."""

    @abstractmethod
    def resolve_xml_path(self, host_path: Path) -> str:
        """Translate a host-side BT XML path to the path the backend sees."""
