"""Tests for the Orchestrator pipeline."""

from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

from defined_cli.compiler import CompileResult, StepInfo
from defined_cli.display import DisplayBase
from defined_cli.errors import BackendError, CompilationError, ConnectionError, TaskExecutionError
from defined_cli.orchestrator import Orchestrator
from defined_cli.target import TargetBase
from defined_cli.transport import TaskProgress, TransportBase

_SAMPLE_RESULT = CompileResult(
    xml_path=Path("/tmp/build/patrol.xml"),
    task_name="PatrolTask",
    steps=[
        StepInfo(verb="go_to", label="GoTo (1.0, 0.0)", index=0),
        StepInfo(verb="report", label="Report", index=1),
    ],
)


@pytest.fixture
def mock_target():
    target = MagicMock(spec=TargetBase)
    target.resolve_xml_path.return_value = "/bt_xml/patrol.xml"
    return target


@pytest.fixture
def mock_transport():
    return MagicMock(spec=TransportBase)


@pytest.fixture
def mock_display():
    return MagicMock(spec=DisplayBase)


@pytest.fixture
def mock_compile():
    fn = MagicMock(return_value=_SAMPLE_RESULT)
    return fn


@pytest.fixture
def task_yaml(tmp_path):
    f = tmp_path / "patrol.task.yaml"
    f.write_text("name: patrol")
    return f


@pytest.fixture
def rdf_yaml(tmp_path):
    f = tmp_path / "robot.rdf.yaml"
    f.write_text("name: test_robot")
    return f


@pytest.fixture
def orch(mock_target, mock_transport, mock_display, mock_compile):
    return Orchestrator(mock_target, mock_transport, mock_display, mock_compile)


def _simulate_success(mock_transport):
    """Make subscribe_status immediately call back with SUCCESS."""
    def fake_subscribe(callback):
        callback(TaskProgress(step="Done", status="SUCCESS", current=5, total=5, progress=100))
    mock_transport.subscribe_status.side_effect = fake_subscribe


def _simulate_failure(mock_transport):
    """Make subscribe_status immediately call back with FAILURE."""
    def fake_subscribe(callback):
        callback(TaskProgress(step="GoTo", status="FAILURE", current=2, total=5, progress=40))
    mock_transport.subscribe_status.side_effect = fake_subscribe


class TestHappyPath:
    def test_call_order(self, orch, mock_target, mock_transport, mock_compile, mock_display, task_yaml, rdf_yaml):
        _simulate_success(mock_transport)
        orch.run(task_yaml, rdf_yaml)

        mock_target.start.assert_called_once()
        mock_transport.connect.assert_called_once()
        mock_compile.assert_called_once()
        mock_transport.send_task.assert_called_once_with("/bt_xml/patrol.xml")
        mock_transport.subscribe_status.assert_called_once()

    def test_display_phases(self, orch, mock_transport, mock_display, task_yaml, rdf_yaml):
        _simulate_success(mock_transport)
        orch.run(task_yaml, rdf_yaml)

        phase_calls = mock_display.show_phase.call_args_list
        phases = [c.args[0] for c in phase_calls]
        assert "Starting" in phases or "Start" in phases
        assert "Connecting" in phases or "Connect" in phases
        assert "Compiling" in phases or "Compile" in phases
        assert "Deploying" in phases or "Deploy" in phases
        assert "Monitoring" in phases or "Monitor" in phases

    def test_success_message(self, orch, mock_transport, mock_display, task_yaml, rdf_yaml):
        _simulate_success(mock_transport)
        orch.run(task_yaml, rdf_yaml)

        mock_display.show_success.assert_called_once()


class TestSkipLaunch:
    def test_skips_target_start(self, orch, mock_target, mock_transport, task_yaml, rdf_yaml):
        _simulate_success(mock_transport)
        orch.run(task_yaml, rdf_yaml, skip_launch=True)

        mock_target.start.assert_not_called()
        mock_transport.connect.assert_called_once()


class TestErrorPropagation:
    def test_backend_error(self, orch, mock_target, task_yaml, rdf_yaml):
        mock_target.start.side_effect = BackendError("Docker not found")
        with pytest.raises(BackendError, match="Docker not found"):
            orch.run(task_yaml, rdf_yaml)

    @patch("defined_cli.orchestrator.time.sleep")
    def test_connection_error(self, mock_sleep, orch, mock_transport, task_yaml, rdf_yaml):
        mock_transport.connect.side_effect = ConnectionError("Refused")
        with pytest.raises(ConnectionError, match="Refused"):
            orch.run(task_yaml, rdf_yaml)

    def test_compilation_error(self, orch, mock_compile, mock_transport, task_yaml, rdf_yaml):
        mock_compile.side_effect = CompilationError("Bad YAML")
        with pytest.raises(CompilationError, match="Bad YAML"):
            orch.run(task_yaml, rdf_yaml)


class TestTaskCompletion:
    def test_failure_raises(self, orch, mock_transport, task_yaml, rdf_yaml):
        _simulate_failure(mock_transport)
        with pytest.raises(TaskExecutionError):
            orch.run(task_yaml, rdf_yaml)

    def test_timeout_raises(self, orch, mock_transport, task_yaml, rdf_yaml):
        # subscribe_status does nothing — event never set
        mock_transport.subscribe_status.side_effect = lambda cb: None
        with pytest.raises(TaskExecutionError, match="timed out"):
            orch.run(task_yaml, rdf_yaml, timeout=0.1)


class TestCleanup:
    def test_disconnect_on_success(self, orch, mock_transport, task_yaml, rdf_yaml):
        _simulate_success(mock_transport)
        orch.run(task_yaml, rdf_yaml)
        mock_transport.disconnect.assert_called_once()

    def test_disconnect_on_error(self, orch, mock_target, mock_transport, task_yaml, rdf_yaml):
        mock_target.start.side_effect = BackendError("fail")
        with pytest.raises(BackendError):
            orch.run(task_yaml, rdf_yaml)
        mock_transport.disconnect.assert_called_once()


class TestConnectRetries:
    @patch("defined_cli.orchestrator.time.sleep")
    def test_retries_on_connection_error(self, mock_sleep, orch, mock_transport, task_yaml, rdf_yaml):
        _simulate_success(mock_transport)
        mock_transport.connect.side_effect = [
            ConnectionError("fail1"),
            ConnectionError("fail2"),
            None,  # success on 3rd try
        ]
        orch.run(task_yaml, rdf_yaml)
        assert mock_transport.connect.call_count == 3
        assert mock_sleep.call_count == 2

    @patch("defined_cli.orchestrator._CONNECT_RETRIES", 3)
    @patch("defined_cli.orchestrator.time.sleep")
    def test_gives_up_after_max_retries(self, mock_sleep, orch, mock_transport, task_yaml, rdf_yaml):
        mock_transport.connect.side_effect = ConnectionError("nope")
        with pytest.raises(ConnectionError):
            orch.run(task_yaml, rdf_yaml)
        assert mock_transport.connect.call_count == 3
