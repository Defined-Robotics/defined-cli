"""Tests for MissionController."""

from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from defined_cli.compiler import CompileResult, StepInfo
from defined_cli.mission.controller import MissionController
from defined_cli.state.model import MissionRecord, RobotStatus
from defined_cli.state.store import StateStore
from defined_cli.target import TargetBase
from defined_cli.transport import TaskProgress, TransportBase
from defined_cli.errors import TransportConnectionError


_SAMPLE_RESULT = CompileResult(
    xml_path=Path("/tmp/build/PatrolTask.xml"),
    task_name="PatrolTask",
    steps=[
        StepInfo(verb="go_to", label="GoTo (1.0, 0.0)", index=0),
        StepInfo(verb="report", label="Report: arrived", index=1),
    ],
)


@pytest.fixture
def mock_transport():
    t = MagicMock(spec=TransportBase)
    t.is_connected = False
    return t


@pytest.fixture
def mock_target():
    t = MagicMock(spec=TargetBase)
    t.resolve_xml_path.return_value = "/bt_xml/PatrolTask.xml"
    return t


@pytest.fixture
def tmp_store(tmp_path):
    return StateStore(path=tmp_path / "state.yaml")


@pytest.fixture
def mock_compile():
    return MagicMock(return_value=_SAMPLE_RESULT)


@pytest.fixture
def controller(mock_transport, tmp_store, mock_compile, mock_target):
    return MissionController(
        store=tmp_store,
        transport=mock_transport,
        compile_fn=mock_compile,
        target=mock_target,
    )


@pytest.fixture
def task_yaml(tmp_path):
    f = tmp_path / "patrol.task.yaml"
    f.write_text("name: PatrolTask\nsteps:\n  - verb: go_to\n    params:\n      x: 1.0\n      y: 0.0\n")
    return f


@pytest.fixture
def rdf_yaml(tmp_path):
    f = tmp_path / "robot.rdf.yaml"
    f.write_text("name: test_robot\nversion: '0.0.1'\ndescription: test\nmodules: []\n")
    return f


def _simulate_success(mock_transport):
    """Make subscribe_status immediately call the callback with SUCCESS."""
    def fake_subscribe(callback):
        callback(TaskProgress(step="Done", status="SUCCESS", current=2, total=2, progress=100))
    mock_transport.subscribe_status.side_effect = fake_subscribe


def _simulate_failure(mock_transport):
    """Make subscribe_status immediately call the callback with FAILURE."""
    def fake_subscribe(callback):
        callback(TaskProgress(step="GoTo", status="FAILURE", current=1, total=2, progress=50))
    mock_transport.subscribe_status.side_effect = fake_subscribe


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------

class TestMissionControllerLifecycle:

    def test_initial_status_is_offline(self, controller):
        assert controller.robot_status == RobotStatus.OFFLINE

    def test_connect_sets_idle(self, controller, mock_transport):
        controller.connect()
        assert controller.robot_status == RobotStatus.IDLE
        mock_transport.connect.assert_called_once()

    def test_disconnect_sets_offline(self, controller, mock_transport):
        controller.connect()
        controller.disconnect()
        assert controller.robot_status == RobotStatus.OFFLINE
        mock_transport.disconnect.assert_called_once()

    def test_connect_saves_state(self, controller, tmp_store):
        controller.connect()
        loaded = tmp_store.load()
        assert loaded.robot.current == RobotStatus.IDLE

    def test_disconnect_saves_state(self, controller, tmp_store):
        controller.connect()
        controller.disconnect()
        loaded = tmp_store.load()
        assert loaded.robot.current == RobotStatus.OFFLINE


# ---------------------------------------------------------------------------
# Mission launch (tested synchronously via _run_mission)
# ---------------------------------------------------------------------------

class TestLaunchMission:

    def test_status_transitions_to_on_mission(self, controller, mock_transport, task_yaml, rdf_yaml):
        """_run_mission sets ON_MISSION before compiling."""
        statuses = []

        original_subscribe = mock_transport.subscribe_status.side_effect

        def capture_status(callback):
            statuses.append(controller.robot_status)
            callback(TaskProgress(step="Done", status="SUCCESS", current=2, total=2, progress=100))

        mock_transport.subscribe_status.side_effect = capture_status
        controller._run_mission(task_yaml, rdf_yaml, None, 30.0)

        assert RobotStatus.ON_MISSION in statuses

    def test_status_returns_idle_on_success(self, controller, mock_transport, task_yaml, rdf_yaml):
        _simulate_success(mock_transport)
        controller._run_mission(task_yaml, rdf_yaml, None, 30.0)
        assert controller.robot_status == RobotStatus.IDLE

    def test_status_returns_idle_on_failure(self, controller, mock_transport, task_yaml, rdf_yaml):
        _simulate_failure(mock_transport)
        controller._run_mission(task_yaml, rdf_yaml, None, 30.0)
        assert controller.robot_status == RobotStatus.IDLE

    def test_mission_record_saved_to_history(self, controller, mock_transport, tmp_store, task_yaml, rdf_yaml):
        _simulate_success(mock_transport)
        controller._run_mission(task_yaml, rdf_yaml, None, 30.0)
        assert len(controller.mission_history) == 1
        record = controller.mission_history[0]
        assert record.task_name == "patrol"
        assert record.status == "SUCCESS"
        assert record.started_at is not None
        assert record.completed_at is not None

    def test_failure_recorded_in_history(self, controller, mock_transport, task_yaml, rdf_yaml):
        _simulate_failure(mock_transport)
        controller._run_mission(task_yaml, rdf_yaml, None, 30.0)
        assert controller.mission_history[0].status == "FAILURE"

    def test_steps_populated_after_compile(self, controller, mock_transport, task_yaml, rdf_yaml):
        _simulate_success(mock_transport)
        controller._run_mission(task_yaml, rdf_yaml, None, 30.0)
        assert controller.steps == _SAMPLE_RESULT.steps

    def test_timeout_results_in_failure(self, controller, mock_transport, task_yaml, rdf_yaml):
        """subscribe_status does nothing — event never fires."""
        mock_transport.subscribe_status.side_effect = lambda cb: None
        controller._run_mission(task_yaml, rdf_yaml, None, 0.05)
        assert controller.robot_status == RobotStatus.IDLE
        assert controller.mission_history[0].status == "FAILURE"

    def test_mission_id_set_on_robot_state(self, controller, mock_transport, tmp_store, task_yaml, rdf_yaml):
        _simulate_success(mock_transport)
        controller._run_mission(task_yaml, rdf_yaml, None, 30.0)
        loaded = tmp_store.load()
        assert loaded.robot.last_mission_id is not None
        assert "patrol" in loaded.robot.last_mission_id

    def test_target_resolves_xml_path_to_container_path(
        self, controller, mock_transport, mock_target, task_yaml, rdf_yaml
    ):
        """When a target is set, send_task must receive the container path, not the host path."""
        _simulate_success(mock_transport)
        controller._run_mission(task_yaml, rdf_yaml, None, 30.0)
        mock_target.resolve_xml_path.assert_called_once_with(_SAMPLE_RESULT.xml_path)
        mock_transport.send_task.assert_called_once_with("/bt_xml/PatrolTask.xml")

    def test_no_target_sends_host_path(
        self, mock_transport, tmp_store, mock_compile, task_yaml, rdf_yaml
    ):
        """Without a target, send_task receives the raw host path."""
        ctrl = MissionController(
            store=tmp_store,
            transport=mock_transport,
            compile_fn=mock_compile,
            target=None,
        )
        _simulate_success(mock_transport)
        ctrl._run_mission(task_yaml, rdf_yaml, None, 30.0)
        mock_transport.send_task.assert_called_once_with(str(_SAMPLE_RESULT.xml_path))


# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------

class TestReports:

    def test_empty_reports_initially(self, controller):
        assert controller.reports == []

    def test_reports_bounded_to_maxlen(self, controller):
        """Overflow the deque to confirm bounded behavior."""
        for i in range(150):
            controller._reports.append(f"msg {i}")
        assert len(controller.reports) <= 100


# ---------------------------------------------------------------------------
# Progress callback
# ---------------------------------------------------------------------------

class TestOnProgress:

    def test_progress_stored(self, controller):
        p = TaskProgress(step="GoTo", status="RUNNING", current=1, total=2, progress=50)
        controller._on_progress(p)
        assert controller.step_progress == p

    def test_done_event_set_on_success(self, controller):
        p = TaskProgress(step="Done", status="SUCCESS", current=2, total=2, progress=100)
        controller._on_progress(p)
        assert controller._done_event.is_set()

    def test_done_event_set_on_failure(self, controller):
        p = TaskProgress(step="GoTo", status="FAILURE", current=1, total=2, progress=50)
        controller._on_progress(p)
        assert controller._done_event.is_set()

    def test_done_event_not_set_on_running(self, controller):
        p = TaskProgress(step="GoTo", status="RUNNING", current=1, total=2, progress=50)
        controller._on_progress(p)
        assert not controller._done_event.is_set()


# ---------------------------------------------------------------------------
# Reconnect
# ---------------------------------------------------------------------------

class TestReconnect:

    @patch("defined_cli.mission.controller.time.sleep")
    def test_reconnect_retries_on_failure(self, mock_sleep, controller, mock_transport):
        mock_transport.connect.side_effect = [
            TransportConnectionError("fail1"),
            TransportConnectionError("fail2"),
            None,  # success on 3rd attempt
        ]
        result = controller.reconnect(max_retries=5, delay=1.0)
        assert result is True
        assert mock_transport.connect.call_count == 3

    @patch("defined_cli.mission.controller.time.sleep")
    def test_reconnect_returns_false_after_max_retries(self, mock_sleep, controller, mock_transport):
        mock_transport.connect.side_effect = TransportConnectionError("always fails")
        result = controller.reconnect(max_retries=3, delay=0.0)
        assert result is False
        assert mock_transport.connect.call_count == 3

    def test_reconnect_sets_idle_on_success(self, controller, mock_transport):
        controller.reconnect(max_retries=1, delay=0.0)
        assert controller.robot_status == RobotStatus.IDLE


# ---------------------------------------------------------------------------
# State properties
# ---------------------------------------------------------------------------

class TestStateProperties:

    def test_pois_empty_initially(self, controller):
        assert controller.pois == {}

    def test_mission_history_empty_initially(self, controller):
        assert controller.mission_history == []

    def test_current_mission_none_initially(self, controller):
        assert controller.current_mission is None

    def test_is_mission_running_false_initially(self, controller):
        assert controller.is_mission_running is False

    def test_last_error_none_initially(self, controller):
        assert controller.last_error is None
