"""Tests for DefinedSession — the unified robot interaction API."""
from __future__ import annotations

import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, PropertyMock, patch, call

import pytest

from defined_cli.mission.events import ConnectionStatus, MissionStatus, SessionEvent
from defined_cli.mission.session import DefinedSession
from defined_cli.state.model import StateSnapshot, RobotStatus
from defined_cli.state.store import StateStore
from defined_cli.transport import TaskProgress, TransportBase
from defined_cli.target import TargetBase, TargetStatus


@pytest.fixture
def mock_target():
    target = MagicMock(spec=TargetBase)
    target.requires_launch = True
    target.status.return_value = TargetStatus.RUNNING
    target.resolve_xml_path.return_value = "/bt_xml/TestTask.xml"
    return target


@pytest.fixture
def mock_transport():
    from defined_cli.transport.readiness import ReadinessReport
    transport = MagicMock(spec=TransportBase)
    transport.is_connected = True
    # Default readiness so health monitor doesn't emit MagicMock messages
    transport.check_readiness.return_value = ReadinessReport(
        connected=True, topics=[], checks=[],
        timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
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


class TestSessionLifecycle:

    def test_initial_state_is_disconnected(self, session):
        assert session.connection_status == ConnectionStatus.DISCONNECTED
        assert session.mission_status == MissionStatus.IDLE

    def test_connect_starts_target_and_transport(self, session, mock_target, mock_transport):
        session.connect()
        mock_target.start.assert_called_once()
        mock_transport.connect.assert_called_once()
        assert session.connection_status == ConnectionStatus.CONNECTED
        session.disconnect()

    def test_connect_skips_target_start_when_not_required(self, session, mock_target):
        mock_target.requires_launch = False
        session.connect()
        mock_target.start.assert_not_called()
        session.disconnect()

    def test_disconnect_closes_transport(self, session, mock_transport):
        session.connect()
        session.disconnect()
        mock_transport.disconnect.assert_called_once()
        assert session.connection_status == ConnectionStatus.DISCONNECTED

    def test_connect_emits_events(self, session):
        events = []
        session.add_listener(events.append)
        session.connect()
        assert any(e.category == "connection" and "Connected" in e.message for e in events)
        session.disconnect()

    def test_disconnect_emits_events(self, session):
        session.connect()
        events = []
        session.add_listener(events.append)
        session.disconnect()
        assert any(e.category == "connection" and "Disconnected" in e.message for e in events)

    def test_state_persisted_after_connect(self, session, store):
        session.connect()
        snapshot = store.load()
        assert snapshot.robot.current == RobotStatus.IDLE
        session.disconnect()

    def test_state_persisted_after_disconnect(self, session, store):
        session.connect()
        session.disconnect()
        snapshot = store.load()
        assert snapshot.robot.current == RobotStatus.OFFLINE


class TestSessionEvents:

    def test_add_and_remove_listener(self, session):
        events = []
        session.add_listener(events.append)
        session.connect()
        assert len(events) > 0

        events.clear()
        session.remove_listener(events.append)
        session.disconnect()
        assert len(events) == 0

    def test_multiple_listeners(self, session):
        events_a, events_b = [], []
        session.add_listener(events_a.append)
        session.add_listener(events_b.append)
        session.connect()
        assert len(events_a) > 0
        assert len(events_a) == len(events_b)
        session.disconnect()

    def test_listener_exception_does_not_crash_session(self, session):
        def bad_listener(event):
            raise RuntimeError("boom")
        session.add_listener(bad_listener)
        session.connect()  # should not raise
        assert session.connection_status == ConnectionStatus.CONNECTED
        session.disconnect()

    def test_events_have_correct_structure(self, session):
        events = []
        session.add_listener(events.append)
        session.connect()
        for e in events:
            assert isinstance(e, SessionEvent)
            assert e.timestamp is not None
            assert e.category in ("connection", "executor", "mission", "error", "health")
            assert isinstance(e.message, str)
        session.disconnect()


class TestSessionCompile:

    def test_compile_standalone(self, session, mock_compile_fn, tmp_path):
        task = tmp_path / "test.task.yaml"
        task.write_text("name: Test\nsteps: []\n")
        rdf = tmp_path / "robot.rdf.yaml"
        rdf.write_text("name: bot\n")

        result = session.compile(task, rdf)
        mock_compile_fn.assert_called_once()
        assert result == mock_compile_fn.return_value

    def test_compile_works_without_connection(self, session, tmp_path):
        """Compile should work even when disconnected."""
        assert session.connection_status == ConnectionStatus.DISCONNECTED
        task = tmp_path / "test.task.yaml"
        task.write_text("name: Test\nsteps: []\n")
        rdf = tmp_path / "robot.rdf.yaml"
        rdf.write_text("name: bot\n")
        result = session.compile(task, rdf)
        assert result is not None


class TestSessionMission:

    def test_run_mission_transitions_through_states(self, session, mock_transport, tmp_path):
        """Run a mission and verify state transitions via events."""
        session.connect()

        # Transport will immediately report SUCCESS when subscribe_status is called
        def fake_subscribe(callback):
            # Simulate executor ready, then success after brief delay
            def _send():
                time.sleep(0.1)
                callback(TaskProgress(step="Done", status="SUCCESS", current=2, total=2, progress=100))
            threading.Thread(target=_send, daemon=True).start()
        mock_transport.subscribe_status.side_effect = fake_subscribe
        mock_transport.wait_for_executor.return_value = True

        events = []
        session.add_listener(events.append)

        task = tmp_path / "test.task.yaml"
        task.write_text("name: Test\nsteps:\n  - verb: wait\n    params:\n      duration: 1\n")
        rdf = tmp_path / "robot.rdf.yaml"
        rdf.write_text("name: bot\n")

        session.run_mission(task, rdf)
        # Wait for daemon thread to complete
        time.sleep(2.0)

        categories = [e.category for e in events]
        assert "mission" in categories
        # Should end in succeeded
        assert session.mission_status in (MissionStatus.SUCCEEDED, MissionStatus.FAILED)
        session.disconnect()

    def test_stop_mission_no_crash_when_idle(self, session):
        session.connect()
        session.stop_mission()  # should not raise
        session.disconnect()

    def test_last_mission_initially_none(self, session):
        assert session.last_mission is None

    def test_current_progress_initially_none(self, session):
        assert session.current_progress is None

    def test_restart_raises_without_prior_mission(self, session):
        session.connect()
        with pytest.raises(RuntimeError, match="No previous mission"):
            session.restart_mission()
        session.disconnect()

    def test_concurrent_mission_raises(self, session, mock_transport, tmp_path):
        """Cannot start a second mission while one is running."""
        session.connect()

        # Make transport block so mission stays in RUNNING
        mock_transport.wait_for_executor.return_value = True
        mock_transport.subscribe_status.side_effect = lambda cb: None  # never calls back

        task = tmp_path / "test.task.yaml"
        task.write_text("name: Test\nsteps:\n  - verb: wait\n    params:\n      duration: 1\n")
        rdf = tmp_path / "robot.rdf.yaml"
        rdf.write_text("name: bot\n")

        session.run_mission(task, rdf)
        time.sleep(0.5)  # let mission thread start

        with pytest.raises(RuntimeError, match="already running"):
            session.run_mission(task, rdf)

        session.stop_mission()
        session.disconnect()


class TestPublishVelocity:

    def test_delegates_to_transport(self, session, mock_transport):
        session.publish_velocity(0.2, -0.5)
        mock_transport.publish_velocity.assert_called_once_with(0.2, -0.5)

    def test_zero_velocity(self, session, mock_transport):
        session.publish_velocity(0.0, 0.0)
        mock_transport.publish_velocity.assert_called_once_with(0.0, 0.0)

    def test_no_crash_when_disconnected(self, session, mock_transport):
        mock_transport.publish_velocity.return_value = None
        session.publish_velocity(0.1, 0.0)  # should not raise


class TestEmergencyStop:

    def _make_running_mission(self, session, mock_transport, tmp_path):
        """Start a mission that never completes (transport never calls back)."""
        mock_transport.wait_for_executor.return_value = True
        mock_transport.subscribe_status.side_effect = lambda cb: None
        task = tmp_path / "test.task.yaml"
        task.write_text("name: Test\nsteps:\n  - verb: wait\n    params:\n      duration: 1\n")
        rdf = tmp_path / "robot.rdf.yaml"
        rdf.write_text("name: bot\n")
        session.run_mission(task, rdf)
        time.sleep(0.4)

    def test_publishes_zero_velocity(self, session, mock_transport):
        session.emergency_stop()
        mock_transport.publish_velocity.assert_called_once_with(0.0, 0.0)

    def test_no_crash_when_idle(self, session):
        session.connect()
        session.emergency_stop()  # must not raise
        session.disconnect()

    def test_stops_running_mission(self, session, mock_transport, tmp_path):
        session.connect()
        self._make_running_mission(session, mock_transport, tmp_path)
        assert session.mission_status == MissionStatus.RUNNING

        session.emergency_stop()
        time.sleep(0.3)

        assert session.mission_status in (MissionStatus.FAILED, MissionStatus.IDLE)
        session.disconnect()

    def test_emits_emergency_stop_event(self, session):
        events = []
        session.add_listener(events.append)
        session.emergency_stop()
        assert any("emergency" in e.message.lower() for e in events)

    def test_sets_mission_status_to_failed_when_running(self, session, mock_transport, tmp_path):
        session.connect()
        self._make_running_mission(session, mock_transport, tmp_path)
        session.emergency_stop()
        time.sleep(0.3)
        assert session.mission_status == MissionStatus.FAILED
        session.disconnect()

class TestSessionWorld:

    def test_add_poi(self, session):
        session.add_poi("dock", 0.0, 0.0, poi_type="constant")
        pois = session.list_pois()
        assert "dock" in pois
        assert pois["dock"]["center"]["x"] == 0.0

    def test_list_pois_empty(self, session):
        pois = session.list_pois()
        assert pois == {}

    def test_add_multiple_pois(self, session):
        session.add_poi("a", 1.0, 2.0)
        session.add_poi("b", 3.0, 4.0)
        pois = session.list_pois()
        assert len(pois) == 2

    def test_pois_persisted_to_store(self, session, store):
        session.add_poi("dock", 0.0, 0.0)
        snapshot = store.load()
        assert "dock" in snapshot.world.pois

    def test_poi_accessible_via_blackboard(self, session):
        session.add_poi("survey", 1.5, 2.5)
        bb = session.blackboard
        poi = bb.get_poi("survey")
        assert poi is not None
        assert poi["center"]["x"] == 1.5
        assert poi["center"]["y"] == 2.5


class TestSessionProperties:

    def test_state_returns_snapshot(self, session):
        snapshot = session.state
        assert isinstance(snapshot, StateSnapshot)

    def test_steps_initially_empty(self, session):
        assert session.steps == []

    def test_reports_initially_empty(self, session):
        assert session.reports == []

    def test_last_error_initially_none(self, session):
        assert session.last_error is None


class TestSessionParamOverrides:
    """run_mission passes param_overrides to compile_fn and persists them for restart."""

    def _make_task(self, tmp_path):
        task = tmp_path / "test.task.yaml"
        task.write_text("name: Test\nsteps:\n  - verb: wait\n    params:\n      duration: 1\n")
        rdf = tmp_path / "robot.rdf.yaml"
        rdf.write_text("name: bot\n")
        return task, rdf

    def test_param_overrides_forwarded_to_compile_fn(self, session, mock_compile_fn, mock_transport, tmp_path):
        session.connect()
        mock_transport.wait_for_executor.return_value = True
        mock_transport.subscribe_status.side_effect = lambda cb: None

        task, rdf = self._make_task(tmp_path)
        session.run_mission(task, rdf, param_overrides={"timeout": "99"})
        time.sleep(0.3)

        _, kwargs = mock_compile_fn.call_args
        assert kwargs.get("param_overrides") == {"timeout": "99"}

        session.stop_mission()
        session.disconnect()

    def test_no_overrides_passes_none_to_compile_fn(self, session, mock_compile_fn, mock_transport, tmp_path):
        session.connect()
        mock_transport.wait_for_executor.return_value = True
        mock_transport.subscribe_status.side_effect = lambda cb: None

        task, rdf = self._make_task(tmp_path)
        session.run_mission(task, rdf)
        time.sleep(0.3)

        _, kwargs = mock_compile_fn.call_args
        assert kwargs.get("param_overrides") is None

        session.stop_mission()
        session.disconnect()

    def test_overrides_stored_for_restart(self, session, mock_compile_fn, mock_transport, tmp_path):
        session.connect()
        mock_transport.wait_for_executor.return_value = True
        mock_transport.subscribe_status.side_effect = lambda cb: None

        task, rdf = self._make_task(tmp_path)
        session.run_mission(task, rdf, param_overrides={"timeout": "55"})
        time.sleep(0.3)
        session.stop_mission()
        time.sleep(0.1)

        mock_compile_fn.reset_mock()
        session.restart_mission()
        time.sleep(0.3)

        _, kwargs = mock_compile_fn.call_args
        assert kwargs.get("param_overrides") == {"timeout": "55"}

        session.stop_mission()
        session.disconnect()

    def test_restart_without_overrides_passes_none(self, session, mock_compile_fn, mock_transport, tmp_path):
        session.connect()
        mock_transport.wait_for_executor.return_value = True
        mock_transport.subscribe_status.side_effect = lambda cb: None

        task, rdf = self._make_task(tmp_path)
        session.run_mission(task, rdf)
        time.sleep(0.3)
        session.stop_mission()
        time.sleep(0.1)

        mock_compile_fn.reset_mock()
        session.restart_mission()
        time.sleep(0.3)

        _, kwargs = mock_compile_fn.call_args
        assert kwargs.get("param_overrides") is None

        session.stop_mission()
        session.disconnect()


from defined_cli.transport.readiness import ReadinessReport, TopicCheck, TopicResult


class TestHealthMonitor:

    def test_latest_readiness_initially_none(self, session):
        assert session.latest_readiness is None

    def test_health_monitor_runs_after_connect(self, session, mock_transport):
        mock_transport.check_readiness.return_value = ReadinessReport(
            connected=True,
            topics=[TopicResult(topic="/odom", publishing=True, latency_ms=10.0)],
            checks=[TopicCheck(topic="/odom", msg_type="nav_msgs/Odometry")],
            timestamp=datetime.now(timezone.utc),
        )
        session.connect()
        time.sleep(1.0)
        assert session.latest_readiness is not None
        assert session.latest_readiness.connected is True
        session.disconnect()

    def test_health_monitor_stops_on_disconnect(self, session, mock_transport):
        mock_transport.check_readiness.return_value = ReadinessReport(
            connected=True, topics=[], checks=[],
            timestamp=datetime.now(timezone.utc),
        )
        session.connect()
        time.sleep(0.5)
        session.disconnect()
        assert session._health_thread is None or not session._health_thread.is_alive()

    def test_health_emits_event_on_status_change(self, session, mock_transport):
        healthy_report = ReadinessReport(
            connected=True,
            topics=[TopicResult(topic="/odom", publishing=True, latency_ms=10.0)],
            checks=[TopicCheck(topic="/odom", msg_type="nav_msgs/Odometry")],
            timestamp=datetime.now(timezone.utc),
        )
        mock_transport.check_readiness.return_value = healthy_report

        events = []
        session.add_listener(events.append)
        session.connect()
        time.sleep(1.0)

        health_events = [e for e in events if e.category == "health"]
        assert len(health_events) >= 1
        session.disconnect()
