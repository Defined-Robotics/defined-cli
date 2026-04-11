"""User-journey tests for DefinedSession — mock transport, real state.

Each test class represents a real user journey:
- Launch TUI, run a patrol, watch it succeed
- Mission fails, user sees error, restarts
- Add POIs, run POI-based patrol
- Emergency stop during a running mission
- Try to run two missions at once
- POIs and history survive session restart
- Robot reports collected during mission

These use mock transport + real StateStore with tmp_path to validate
session-level logic without Docker/rosbridge. For true e2e tests
against a running sim stack, see ``tests/integration/``.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from defined_cli.mission.events import ConnectionStatus, MissionStatus, SessionEvent
from defined_cli.mission.session import DefinedSession
from defined_cli.state.model import RobotStatus, StateSnapshot
from defined_cli.state.store import StateStore
from defined_cli.target import TargetBase, TargetStatus
from defined_cli.transport import TaskProgress, TransportBase


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_target():
    target = MagicMock(spec=TargetBase)
    target.requires_launch = True
    target.status.return_value = TargetStatus.RUNNING
    target.resolve_xml_path.return_value = "/bt_xml/TestTask.xml"
    return target


@pytest.fixture
def mock_transport():
    transport = MagicMock(spec=TransportBase)
    transport.is_connected = True
    return transport


@pytest.fixture
def store(tmp_path):
    return StateStore(path=tmp_path / "state.yaml")


@pytest.fixture
def mock_compile_fn(tmp_path):
    result = MagicMock()
    result.xml_path = tmp_path / "TestTask.xml"
    result.xml_path.write_text("<root/>")
    result.steps = [
        MagicMock(index=0, label="GoTo (1.0, 0.0)"),
        MagicMock(index=1, label="Report checkpoint"),
    ]
    result.task_name = "TestTask"
    fn = MagicMock(return_value=result)
    return fn


@pytest.fixture
def session(mock_target, mock_transport, store, mock_compile_fn):
    return DefinedSession(
        target=mock_target,
        transport=mock_transport,
        store=store,
        compile_fn=mock_compile_fn,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_task(tmp_path: Path) -> tuple[Path, Path]:
    """Write a minimal task + RDF YAML and return (task, rdf) paths."""
    task = tmp_path / "patrol.task.yaml"
    task.write_text(
        "name: Patrol\nsteps:\n"
        "  - verb: go_to\n    params:\n      target: {x: 1.0, y: 0.0}\n"
        "  - verb: report\n    params:\n      message: arrived\n"
    )
    rdf = tmp_path / "robot.rdf.yaml"
    rdf.write_text("name: test-bot\n")
    return task, rdf


def _make_poi_task(tmp_path: Path) -> tuple[Path, Path]:
    """Write a task that references $world.pois.dock."""
    task = tmp_path / "poi_patrol.task.yaml"
    task.write_text(
        "name: POIPatrol\nsteps:\n"
        "  - verb: go_to\n    params:\n      target: $world.pois.dock\n"
    )
    rdf = tmp_path / "robot.rdf.yaml"
    if not rdf.exists():
        rdf.write_text("name: test-bot\n")
    return task, rdf


def _simulate_success(mock_transport: MagicMock) -> None:
    """Configure transport to fire SUCCESS after a brief delay."""
    mock_transport.wait_for_executor.return_value = True

    def _fake_subscribe(callback: Callable) -> None:
        def _send():
            time.sleep(0.1)
            callback(TaskProgress(
                step="Done", status="SUCCESS", current=2, total=2, progress=100,
            ))
        threading.Thread(target=_send, daemon=True).start()

    mock_transport.subscribe_status.side_effect = _fake_subscribe


def _simulate_failure(mock_transport: MagicMock) -> None:
    """Configure transport to fire FAILURE after a brief delay."""
    mock_transport.wait_for_executor.return_value = True

    def _fake_subscribe(callback: Callable) -> None:
        def _send():
            time.sleep(0.1)
            callback(TaskProgress(
                step="GoTo", status="FAILURE", current=1, total=2, progress=0,
            ))
        threading.Thread(target=_send, daemon=True).start()

    mock_transport.subscribe_status.side_effect = _fake_subscribe


def _simulate_hang(mock_transport: MagicMock) -> None:
    """Configure transport to never call back (mission hangs until stopped)."""
    mock_transport.wait_for_executor.return_value = True
    mock_transport.subscribe_status.side_effect = lambda cb: None


def _wait_for_status(session: DefinedSession, status: MissionStatus, timeout: float = 3.0) -> bool:
    """Poll until session reaches the given mission status."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if session.mission_status == status:
            return True
        time.sleep(0.05)
    return False


# ---------------------------------------------------------------------------
# Journey 1: Happy path
# ---------------------------------------------------------------------------


class TestFirstMissionFlow:
    """User launches TUI, runs a patrol, watches it succeed, checks history."""

    def test_connect_run_succeed_disconnect(self, session, mock_transport, store, tmp_path):
        session.connect()
        _simulate_success(mock_transport)
        task, rdf = _make_task(tmp_path)

        session.run_mission(task, rdf)
        assert _wait_for_status(session, MissionStatus.SUCCEEDED)

        # State store has mission in history
        snapshot = store.load()
        assert len(snapshot.mission_history) == 1
        record = snapshot.mission_history[0]
        assert record.result == "SUCCESS"
        assert record.started_at is not None
        assert record.completed_at is not None
        assert snapshot.robot.current == RobotStatus.IDLE

        session.disconnect()
        assert session.connection_status == ConnectionStatus.DISCONNECTED

    def test_run_second_mission_after_first_completes(self, session, mock_transport, store, tmp_path):
        session.connect()
        _simulate_success(mock_transport)
        task, rdf = _make_task(tmp_path)

        # First mission
        session.run_mission(task, rdf)
        assert _wait_for_status(session, MissionStatus.SUCCEEDED)

        # Second mission
        _simulate_success(mock_transport)
        session.run_mission(task, rdf)
        assert _wait_for_status(session, MissionStatus.SUCCEEDED)

        snapshot = store.load()
        assert len(snapshot.mission_history) == 2

        session.disconnect()


# ---------------------------------------------------------------------------
# Journey 2: Failure and recovery
# ---------------------------------------------------------------------------


class TestFailureAndRecovery:
    """User runs a mission, it fails, they see the error, they restart."""

    def test_mission_fails_user_sees_error_and_restarts(self, session, mock_transport, store, tmp_path):
        session.connect()
        task, rdf = _make_task(tmp_path)

        # First attempt: FAILURE
        _simulate_failure(mock_transport)
        session.run_mission(task, rdf)
        assert _wait_for_status(session, MissionStatus.FAILED)

        snapshot = store.load()
        assert snapshot.mission_history[-1].result == "FAILURE"

        # Restart with transport now reporting SUCCESS
        _simulate_success(mock_transport)
        session.restart_mission()
        assert _wait_for_status(session, MissionStatus.SUCCEEDED)

        snapshot = store.load()
        assert len(snapshot.mission_history) == 2
        assert snapshot.mission_history[-1].result == "SUCCESS"

        session.disconnect()

    def test_mission_timeout_user_retries(self, session, mock_transport, store, tmp_path):
        session.connect()
        _simulate_hang(mock_transport)
        task, rdf = _make_task(tmp_path)

        events: list[SessionEvent] = []
        session.add_listener(events.append)

        session.run_mission(task, rdf, timeout=0.5)
        assert _wait_for_status(session, MissionStatus.FAILED, timeout=5.0)

        snapshot = store.load()
        assert snapshot.mission_history[-1].result == "TIMEOUT"

        # Error event mentions timeout
        error_events = [e for e in events if e.category == "error"]
        assert any("timed out" in e.message.lower() for e in error_events)

        session.disconnect()


# ---------------------------------------------------------------------------
# Journey 3: POI workflow
# ---------------------------------------------------------------------------


class TestPOIWorkflow:
    """User adds POIs, runs a patrol that references them."""

    def test_add_pois_then_run_poi_patrol(self, session, mock_transport, mock_compile_fn, tmp_path):
        session.connect()
        _simulate_success(mock_transport)

        # Add POIs
        session.add_poi("dock", 0.0, 0.0, poi_type="constant")
        session.add_poi("survey-1", 1.5, 2.0)

        # Run POI-referencing task
        task, rdf = _make_poi_task(tmp_path)
        session.run_mission(task, rdf)
        assert _wait_for_status(session, MissionStatus.SUCCEEDED)

        # Verify compile_fn was called with a resolved path (not original task)
        call_args = mock_compile_fn.call_args[0]
        resolved_path = call_args[0]
        assert resolved_path != task  # resolved to a temp file
        # Temp file should be cleaned up
        assert not resolved_path.exists()

        session.disconnect()

    def test_missing_poi_gives_actionable_error(self, session, mock_transport, tmp_path):
        session.connect()

        events: list[SessionEvent] = []
        session.add_listener(events.append)

        task, rdf = _make_poi_task(tmp_path)  # references $world.pois.dock — not defined
        session.run_mission(task, rdf)
        assert _wait_for_status(session, MissionStatus.FAILED)

        assert session.last_error is not None
        assert "dock" in session.last_error.lower() or "pois" in session.last_error.lower()

        error_events = [e for e in events if e.category == "error"]
        assert any("poi" in e.message.lower() for e in error_events)

        session.disconnect()


# ---------------------------------------------------------------------------
# Journey 4: Emergency stop
# ---------------------------------------------------------------------------


class TestEmergencyStopJourney:
    """User is running a mission, something goes wrong, they hit e-stop."""

    def test_estop_halts_running_mission(self, session, mock_transport, tmp_path):
        session.connect()
        _simulate_hang(mock_transport)
        task, rdf = _make_task(tmp_path)

        events: list[SessionEvent] = []
        session.add_listener(events.append)

        session.run_mission(task, rdf)
        assert _wait_for_status(session, MissionStatus.RUNNING)

        session.emergency_stop()

        # BT executor told to stop before zero velocity
        mock_transport.cancel_task.assert_called_once()
        # Zero velocity published
        mock_transport.publish_velocity.assert_called_with(0.0, 0.0)

        # Mission terminates
        assert _wait_for_status(session, MissionStatus.FAILED)

        # Event emitted
        assert any("emergency" in e.message.lower() for e in events)

        session.disconnect()

    def test_estop_safe_when_idle(self, session, mock_transport, tmp_path):
        session.connect()

        # E-stop when no mission running — cancel_task still called (belt-and-suspenders)
        session.emergency_stop()
        mock_transport.cancel_task.assert_called_once()
        mock_transport.publish_velocity.assert_called_with(0.0, 0.0)

        # Can still run a mission afterwards
        _simulate_success(mock_transport)
        task, rdf = _make_task(tmp_path)
        session.run_mission(task, rdf)
        assert _wait_for_status(session, MissionStatus.SUCCEEDED)

        session.disconnect()


# ---------------------------------------------------------------------------
# Journey 5: Concurrent mission guard
# ---------------------------------------------------------------------------


class TestConcurrentGuard:
    """User tries to run two missions at once — system prevents it."""

    def test_cannot_start_second_mission_while_running(self, session, mock_transport, tmp_path):
        session.connect()
        _simulate_hang(mock_transport)
        task, rdf = _make_task(tmp_path)

        session.run_mission(task, rdf)
        assert _wait_for_status(session, MissionStatus.RUNNING)

        with pytest.raises(RuntimeError, match="already running"):
            session.run_mission(task, rdf)

        # Clean up: stop first mission, then verify a new one can start
        session.stop_mission()
        assert _wait_for_status(session, MissionStatus.FAILED)

        _simulate_success(mock_transport)
        session.run_mission(task, rdf)
        assert _wait_for_status(session, MissionStatus.SUCCEEDED)

        session.disconnect()


# ---------------------------------------------------------------------------
# Journey 6: State persistence
# ---------------------------------------------------------------------------


class TestStatePersistence:
    """User adds POIs, runs missions, closes CLI, reopens — state is there."""

    def test_pois_and_history_survive_session_restart(
        self, mock_target, mock_transport, mock_compile_fn, tmp_path,
    ):
        state_file = tmp_path / "state.yaml"
        store1 = StateStore(path=state_file)
        session1 = DefinedSession(
            target=mock_target,
            transport=mock_transport,
            store=store1,
            compile_fn=mock_compile_fn,
        )

        session1.connect()
        session1.add_poi("dock", 0.0, 0.0, poi_type="constant")
        session1.add_poi("survey-1", 1.5, 2.0)

        _simulate_success(mock_transport)
        task, rdf = _make_task(tmp_path)
        session1.run_mission(task, rdf)
        assert _wait_for_status(session1, MissionStatus.SUCCEEDED)
        session1.disconnect()

        # Simulate reopening the CLI — new StateStore, new session, same file
        store2 = StateStore(path=state_file)
        session2 = DefinedSession(
            target=mock_target,
            transport=mock_transport,
            store=store2,
            compile_fn=mock_compile_fn,
        )

        pois = session2.list_pois()
        assert "dock" in pois
        assert "survey-1" in pois
        assert pois["dock"]["center"]["x"] == 0.0
        assert pois["survey-1"]["center"]["x"] == 1.5

        snapshot = store2.load()
        assert len(snapshot.mission_history) == 1
        assert snapshot.mission_history[0].result == "SUCCESS"


# ---------------------------------------------------------------------------
# Journey 7: Reports
# ---------------------------------------------------------------------------


class TestReportCollection:
    """Robot sends reports during mission, user sees them."""

    def test_reports_collected_during_mission(self, session, mock_transport, tmp_path):
        session.connect()

        # Capture the subscribe_reports callback
        report_callback = None

        def _capture_cb(cb):
            nonlocal report_callback
            report_callback = cb

        mock_transport.subscribe_reports.side_effect = _capture_cb
        # Re-connect to trigger subscribe_reports with our capture
        session.disconnect()
        session.connect()

        assert report_callback is not None

        events: list[SessionEvent] = []
        session.add_listener(events.append)

        # Inject report messages
        report_callback("arrived at survey-1")
        report_callback("scan complete")

        assert "arrived at survey-1" in session.reports
        assert "scan complete" in session.reports

        report_events = [e for e in events if "Report:" in e.message]
        assert len(report_events) == 2

        session.disconnect()
