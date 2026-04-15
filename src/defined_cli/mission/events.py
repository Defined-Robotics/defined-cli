"""Mission event types — connection states, mission states, and session events.

Pure data types with no I/O, no CLI dependencies, and no side effects.
Used by ``DefinedSession`` for lifecycle tracking and by TUI/scripts
for observing state changes.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Literal


class ConnectionStatus(Enum):
    """Transport connection lifecycle states."""

    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    RECONNECTING = "reconnecting"


class MissionStatus(Enum):
    """Mission execution lifecycle states."""

    IDLE = "idle"
    COMPILING = "compiling"
    DEPLOYING = "deploying"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


@dataclass(frozen=True)
class SessionEvent:
    """Structured event emitted by DefinedSession.

    Attributes:
        timestamp: When the event occurred (UTC).
        category: Event category for filtering/routing.
        message: Human-readable description (Layer 1).
        suggestion: Actionable hint (Layer 2), or None.
        detail: Structured data (Layer 3), or None.
    """

    timestamp: datetime
    category: Literal["connection", "executor", "mission", "error", "health"]
    message: str
    suggestion: str | None
    detail: dict[str, Any] | None
