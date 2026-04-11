"""Tests for DockerImageTarget — manages pre-built Docker images via docker run.

Covers:
- Start runs docker with correct image and port mapping
- Start passes world env variable when set
- Stop removes container
- Resolve XML path returns /bt_xml/ prefix
- Start when container exists → removes first
- Status parsing from docker inspect
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

from defined_cli.target import TargetStatus
from defined_cli.target.docker_image import DockerImageTarget


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


class TestDockerImageTargetInit:

    def test_default_port(self) -> None:
        target = DockerImageTarget(image="ghcr.io/defined-robotics/sim:0.1.0")
        assert target._image == "ghcr.io/defined-robotics/sim:0.1.0"
        assert target._port == 9090

    def test_custom_port(self) -> None:
        target = DockerImageTarget(image="my-image:latest", port=9091)
        assert target._port == 9091

    def test_world_env(self) -> None:
        target = DockerImageTarget(image="my-image:latest", world_env="maze_10x10")
        assert target._world_env == "maze_10x10"


# ---------------------------------------------------------------------------
# start()
# ---------------------------------------------------------------------------


class TestDockerImageTargetStart:

    @patch("defined_cli.target.docker_image.subprocess")
    def test_start_runs_docker_run(self, mock_subprocess: MagicMock) -> None:
        """start() calls docker run with correct image, port, and volume."""
        mock_subprocess.run.return_value = MagicMock(returncode=0)

        target = DockerImageTarget(image="ghcr.io/defined-robotics/sim:0.1.0")
        target.start()

        # Should have called docker run
        calls = mock_subprocess.run.call_args_list
        run_call = [c for c in calls if "run" in c[0][0]]
        assert len(run_call) >= 1
        cmd = run_call[-1][0][0]
        assert "docker" in cmd
        assert "-p" in cmd or any("9090" in str(a) for a in cmd)

    @patch("defined_cli.target.docker_image.subprocess")
    def test_start_passes_world_env(self, mock_subprocess: MagicMock) -> None:
        """start() passes WORLD_NAME env var when world_env is set."""
        mock_subprocess.run.return_value = MagicMock(returncode=0)

        target = DockerImageTarget(
            image="my-image:latest",
            world_env="warehouse",
        )
        target.start()

        # Find the docker run call
        calls = mock_subprocess.run.call_args_list
        all_args = []
        for c in calls:
            all_args.extend(c[0][0])
        args_str = " ".join(str(a) for a in all_args)
        assert "WORLD_NAME" in args_str
        assert "warehouse" in args_str

    @patch("defined_cli.target.docker_image.subprocess")
    def test_start_removes_existing_container(self, mock_subprocess: MagicMock) -> None:
        """start() removes existing container before starting a new one."""
        mock_subprocess.run.return_value = MagicMock(returncode=0, stdout="")

        target = DockerImageTarget(image="my-image:latest")
        target.start()

        # Should call docker rm before docker run
        calls = mock_subprocess.run.call_args_list
        cmds = [c[0][0] for c in calls]
        # Find rm and run commands
        rm_indices = [i for i, cmd in enumerate(cmds) if "rm" in cmd]
        run_indices = [i for i, cmd in enumerate(cmds) if "run" in cmd and "-d" in cmd]
        assert len(rm_indices) >= 1
        assert len(run_indices) >= 1
        # rm should come before run
        assert rm_indices[0] < run_indices[0]


# ---------------------------------------------------------------------------
# stop()
# ---------------------------------------------------------------------------


class TestDockerImageTargetStop:

    @patch("defined_cli.target.docker_image.subprocess")
    def test_stop_removes_container(self, mock_subprocess: MagicMock) -> None:
        """stop() calls docker stop + docker rm."""
        mock_subprocess.run.return_value = MagicMock(returncode=0)

        target = DockerImageTarget(image="my-image:latest")
        target.stop()

        calls = mock_subprocess.run.call_args_list
        all_cmds = [c[0][0] for c in calls]
        # Should have stop and rm
        stop_calls = [cmd for cmd in all_cmds if "stop" in cmd]
        rm_calls = [cmd for cmd in all_cmds if "rm" in cmd]
        assert len(stop_calls) >= 1
        assert len(rm_calls) >= 1


# ---------------------------------------------------------------------------
# status()
# ---------------------------------------------------------------------------


class TestDockerImageTargetStatus:

    @patch("defined_cli.target.docker_image.subprocess")
    def test_status_running(self, mock_subprocess: MagicMock) -> None:
        """status() returns RUNNING when container is running."""
        mock_subprocess.run.return_value = MagicMock(
            returncode=0,
            stdout='{"State":{"Status":"running"}}',
        )

        target = DockerImageTarget(image="my-image:latest")
        assert target.status() == TargetStatus.RUNNING

    @patch("defined_cli.target.docker_image.subprocess")
    def test_status_stopped_no_container(self, mock_subprocess: MagicMock) -> None:
        """status() returns STOPPED when container doesn't exist."""
        import subprocess as sp
        mock_subprocess.CalledProcessError = sp.CalledProcessError
        mock_subprocess.run.side_effect = sp.CalledProcessError(1, "docker inspect")

        target = DockerImageTarget(image="my-image:latest")
        assert target.status() == TargetStatus.STOPPED

    @patch("defined_cli.target.docker_image.subprocess")
    def test_status_exited(self, mock_subprocess: MagicMock) -> None:
        """status() returns STOPPED when container has exited."""
        mock_subprocess.run.return_value = MagicMock(
            returncode=0,
            stdout='{"State":{"Status":"exited"}}',
        )

        target = DockerImageTarget(image="my-image:latest")
        assert target.status() == TargetStatus.STOPPED


# ---------------------------------------------------------------------------
# resolve_xml_path()
# ---------------------------------------------------------------------------


class TestResolveXmlPath:

    def test_resolve_xml_path(self) -> None:
        """resolve_xml_path returns /bt_xml/<filename>."""
        target = DockerImageTarget(image="my-image:latest")
        result = target.resolve_xml_path(Path("/tmp/output/patrol.xml"))
        assert result == "/bt_xml/patrol.xml"
