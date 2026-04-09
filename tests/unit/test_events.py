"""Tests for mission event types."""
from __future__ import annotations

from datetime import datetime, timezone

from defined_cli.mission.events import (
    ConnectionStatus,
    MissionStatus,
    SessionEvent,
)


class TestConnectionStatus:

    def test_has_all_states(self):
        assert ConnectionStatus.DISCONNECTED.value == "disconnected"
        assert ConnectionStatus.CONNECTING.value == "connecting"
        assert ConnectionStatus.CONNECTED.value == "connected"
        assert ConnectionStatus.RECONNECTING.value == "reconnecting"

    def test_is_iterable(self):
        assert len(list(ConnectionStatus)) == 4


class TestMissionStatus:

    def test_has_all_states(self):
        assert MissionStatus.IDLE.value == "idle"
        assert MissionStatus.COMPILING.value == "compiling"
        assert MissionStatus.DEPLOYING.value == "deploying"
        assert MissionStatus.RUNNING.value == "running"
        assert MissionStatus.SUCCEEDED.value == "succeeded"
        assert MissionStatus.FAILED.value == "failed"

    def test_is_iterable(self):
        assert len(list(MissionStatus)) == 6


class TestSessionEvent:

    def test_creation_with_all_fields(self):
        ts = datetime.now(timezone.utc)
        event = SessionEvent(
            timestamp=ts,
            category="mission",
            message="Task completed",
            suggestion="Run /restart to try again",
            detail={"step": 3, "verb": "GoTo"},
        )
        assert event.timestamp == ts
        assert event.category == "mission"
        assert event.message == "Task completed"
        assert event.suggestion == "Run /restart to try again"
        assert event.detail == {"step": 3, "verb": "GoTo"}

    def test_creation_minimal(self):
        event = SessionEvent(
            timestamp=datetime.now(timezone.utc),
            category="connection",
            message="Connected to sim",
            suggestion=None,
            detail=None,
        )
        assert event.suggestion is None
        assert event.detail is None

    def test_is_frozen(self):
        event = SessionEvent(
            timestamp=datetime.now(timezone.utc),
            category="error",
            message="test",
            suggestion=None,
            detail=None,
        )
        import dataclasses
        assert dataclasses.is_dataclass(event)
        try:
            event.message = "changed"  # type: ignore[misc]
            assert False, "Should not be able to set attribute on frozen dataclass"
        except (AttributeError, dataclasses.FrozenInstanceError):
            pass

    def test_all_valid_categories(self):
        """Ensure all four categories can be instantiated."""
        for cat in ("connection", "executor", "mission", "error"):
            event = SessionEvent(
                timestamp=datetime.now(timezone.utc),
                category=cat,
                message=f"test {cat}",
                suggestion=None,
                detail=None,
            )
            assert event.category == cat
