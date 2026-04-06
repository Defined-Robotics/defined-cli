"""Tests for SimTarget — docker compose lifecycle management."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from defined_cli.errors import BackendError
from defined_cli.target import TargetStatus
from defined_cli.target.sim import SimTarget


@pytest.fixture
def target(tmp_path: Path) -> SimTarget:
    """SimTarget with a fake compose file."""
    compose = tmp_path / "docker-compose.yml"
    compose.write_text("services: {}")
    return SimTarget(compose_file=compose)


class TestResolveXmlPath:
    def test_extracts_filename(self, target: SimTarget) -> None:
        result = target.resolve_xml_path(Path("/some/host/path/patrol.xml"))
        assert result == "/bt_xml/patrol.xml"

    def test_nested_path(self, target: SimTarget) -> None:
        result = target.resolve_xml_path(Path("build/deep/task.xml"))
        assert result == "/bt_xml/task.xml"


class TestStart:
    @patch("defined_cli.target.sim.subprocess.run")
    def test_calls_docker_compose_up(self, mock_run, target: SimTarget) -> None:
        target.start()
        args = mock_run.call_args[0][0]
        assert args[:2] == ["docker", "compose"]
        assert "up" in args
        assert "-d" in args

    @patch("defined_cli.target.sim.subprocess.run", side_effect=FileNotFoundError("docker"))
    def test_raises_backend_error_when_docker_missing(self, _mock, target: SimTarget) -> None:
        with pytest.raises(BackendError, match="not installed"):
            target.start()

    @patch(
        "defined_cli.target.sim.subprocess.run",
        side_effect=subprocess.CalledProcessError(1, "docker", stderr="daemon not running"),
    )
    def test_raises_backend_error_on_failure(self, _mock, target: SimTarget) -> None:
        with pytest.raises(BackendError, match="command failed"):
            target.start()


class TestStop:
    @patch("defined_cli.target.sim.subprocess.run")
    def test_calls_docker_compose_down(self, mock_run, target: SimTarget) -> None:
        target.stop()
        args = mock_run.call_args[0][0]
        assert "down" in args


class TestStatus:
    @patch("defined_cli.target.sim.subprocess.run")
    def test_running(self, mock_run, target: SimTarget) -> None:
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0,
            stdout=json.dumps({"Name": "defined_sim", "State": "running"}) + "\n",
        )
        assert target.status() == TargetStatus.RUNNING

    @patch("defined_cli.target.sim.subprocess.run")
    def test_stopped_empty_output(self, mock_run, target: SimTarget) -> None:
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="",
        )
        assert target.status() == TargetStatus.STOPPED

    @patch("defined_cli.target.sim.subprocess.run")
    def test_starting_state(self, mock_run, target: SimTarget) -> None:
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0,
            stdout=json.dumps({"Name": "defined_sim", "State": "created"}) + "\n",
        )
        assert target.status() == TargetStatus.STARTING


class TestFindComposeFile:
    def test_raises_when_not_found(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.chdir(tmp_path)
        with pytest.raises(BackendError, match="Cannot find"):
            SimTarget()
