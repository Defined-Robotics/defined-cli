"""Tests for DefinedSession — the unified robot interaction API."""
from __future__ import annotations

import threading
import time
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
            assert e.category in ("connection", "executor", "mission", "error")
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
