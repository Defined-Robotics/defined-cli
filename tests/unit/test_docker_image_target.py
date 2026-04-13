"""Tests for DockerImageTarget — manages pre-built Docker images via docker-py.

Covers:
- Construction with various option combinations
- Start lifecycle (container creation, bind mounts, env vars, stale removal)
- Stop lifecycle (container removal)
- Status parsing from Docker API
- BT XML path resolution (host → container)
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import docker.errors
import pytest

from defined_cli.errors import BackendError
from defined_cli.target import TargetStatus
from defined_cli.target.docker_image import DockerImageTarget


@pytest.fixture()
def mock_client():
    """Provide a mocked docker.DockerClient for all tests."""
    with patch("defined_cli.target.docker_image._get_client") as mock_get:
        client = MagicMock()
        mock_get.return_value = client
        # containers.get raises NotFound by default (no stale container)
        client.containers.get.side_effect = docker.errors.NotFound("gone")
        yield client


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


class TestDockerImageTargetInit:

    def test_default_port(self, mock_client: MagicMock) -> None:
        """Preconditions: No arguments beyond image.
        Tests: Default port is 9090.
        Success: _port attribute equals 9090.
        """
        target = DockerImageTarget(image="ghcr.io/defined-robotics/sim:0.1.0")
        assert target._port == 9090

    def test_custom_port(self, mock_client: MagicMock) -> None:
        """Preconditions: Custom port provided.
        Tests: Port override is stored.
        Success: _port attribute equals the custom value.
        """
        target = DockerImageTarget(image="my-image:latest", port=9091)
        assert target._port == 9091

    def test_world_env(self, mock_client: MagicMock) -> None:
        """Preconditions: world_env provided.
        Tests: World environment is stored for later use in start().
        Success: _world_env attribute equals the provided value.
        """
        target = DockerImageTarget(image="my-image:latest", world_env="maze_10x10")
        assert target._world_env == "maze_10x10"

    def test_bt_xml_dir(self, mock_client: MagicMock) -> None:
        """Preconditions: bt_xml_dir provided.
        Tests: BT XML host directory is stored for bind mount.
        Success: _bt_xml_dir attribute equals the provided path.
        """
        target = DockerImageTarget(image="my-image:latest", bt_xml_dir=Path("/tmp/bt"))
        assert target._bt_xml_dir == Path("/tmp/bt")


# ---------------------------------------------------------------------------
# start()
# ---------------------------------------------------------------------------


class TestDockerImageTargetStart:

    def test_start_runs_container(self, mock_client: MagicMock) -> None:
        """Preconditions: No existing container (get raises NotFound).
        Tests: start() calls containers.run with correct image and port.
        Success: containers.run called once with expected image, name, port mapping.
        """
        target = DockerImageTarget(image="ghcr.io/defined-robotics/sim:0.1.0")
        target.start()

        mock_client.containers.run.assert_called_once()
        call_kwargs = mock_client.containers.run.call_args
        assert call_kwargs[0][0] == "ghcr.io/defined-robotics/sim:0.1.0"
        assert call_kwargs[1]["name"] == "defined_sim"
        assert call_kwargs[1]["detach"] is True
        assert call_kwargs[1]["ports"] == {"9090/tcp": 9090, "8765/tcp": 8765}

    def test_start_passes_world_env(self, mock_client: MagicMock) -> None:
        """Preconditions: world_env is set to 'warehouse'.
        Tests: start() passes WORLD_NAME as environment variable.
        Success: containers.run receives environment={'WORLD_NAME': 'warehouse'}.
        """
        target = DockerImageTarget(image="my-image:latest", world_env="warehouse")
        target.start()

        call_kwargs = mock_client.containers.run.call_args[1]
        assert call_kwargs["environment"] == {"WORLD_NAME": "warehouse"}

    def test_start_bind_mounts_bt_xml_dir(self, mock_client: MagicMock, tmp_path: Path) -> None:
        """Preconditions: bt_xml_dir points to a host directory.
        Tests: start() creates a bind mount from host dir to /bt_xml.
        Success: containers.run receives volumes dict with correct bind mount.
        """
        bt_dir = tmp_path / "bt_xml"
        target = DockerImageTarget(image="my-image:latest", bt_xml_dir=bt_dir)
        target.start()

        call_kwargs = mock_client.containers.run.call_args[1]
        assert str(bt_dir) in call_kwargs["volumes"]
        mount = call_kwargs["volumes"][str(bt_dir)]
        assert mount["bind"] == "/bt_xml"
        assert mount["mode"] == "rw"

    def test_start_creates_bt_xml_dir_if_missing(self, mock_client: MagicMock, tmp_path: Path) -> None:
        """Preconditions: bt_xml_dir does not exist yet.
        Tests: start() creates the directory before mounting.
        Success: Directory exists after start().
        """
        bt_dir = tmp_path / "nonexistent" / "bt_xml"
        target = DockerImageTarget(image="my-image:latest", bt_xml_dir=bt_dir)
        target.start()

        assert bt_dir.exists()

    def test_start_no_volumes_when_bt_xml_dir_is_none(self, mock_client: MagicMock) -> None:
        """Preconditions: bt_xml_dir is None (not provided).
        Tests: start() passes None for volumes (no bind mount).
        Success: containers.run receives volumes=None.
        """
        target = DockerImageTarget(image="my-image:latest")
        target.start()

        call_kwargs = mock_client.containers.run.call_args[1]
        assert call_kwargs["volumes"] is None

    def test_start_removes_existing_container(self, mock_client: MagicMock) -> None:
        """Preconditions: A stale container named 'defined_sim' exists.
        Tests: start() stops and removes it before creating a new one.
        Success: container.stop() and container.remove() called before containers.run().
        """
        stale = MagicMock()
        mock_client.containers.get.side_effect = None
        mock_client.containers.get.return_value = stale

        target = DockerImageTarget(image="my-image:latest")
        target.start()

        stale.stop.assert_called_once()
        stale.remove.assert_called_once()
        mock_client.containers.run.assert_called_once()

    def test_start_raises_on_image_not_found(self, mock_client: MagicMock) -> None:
        """Preconditions: Docker image does not exist locally or in registry.
        Tests: start() raises BackendError with pull suggestion.
        Success: BackendError raised with image name in message.
        """
        mock_client.containers.run.side_effect = docker.errors.ImageNotFound("nope")

        target = DockerImageTarget(image="missing:latest")
        with pytest.raises(BackendError, match="Docker image not found"):
            target.start()


# ---------------------------------------------------------------------------
# stop()
# ---------------------------------------------------------------------------


class TestDockerImageTargetStop:

    def test_stop_removes_container(self, mock_client: MagicMock) -> None:
        """Preconditions: Container 'defined_sim' is running.
        Tests: stop() stops and removes the container.
        Success: container.stop() and container.remove() both called.
        """
        container = MagicMock()
        mock_client.containers.get.side_effect = None
        mock_client.containers.get.return_value = container

        target = DockerImageTarget(image="my-image:latest")
        target.stop()

        container.stop.assert_called_once()
        container.remove.assert_called_once()

    def test_stop_ignores_missing_container(self, mock_client: MagicMock) -> None:
        """Preconditions: No container exists (already removed).
        Tests: stop() silently succeeds when container is gone.
        Success: No exception raised.
        """
        target = DockerImageTarget(image="my-image:latest")
        target.stop()  # containers.get raises NotFound by default


# ---------------------------------------------------------------------------
# status()
# ---------------------------------------------------------------------------


class TestDockerImageTargetStatus:

    def test_status_running(self, mock_client: MagicMock) -> None:
        """Preconditions: Container exists with status 'running'.
        Tests: status() returns TargetStatus.RUNNING.
        Success: Return value is TargetStatus.RUNNING.
        """
        container = MagicMock()
        container.status = "running"
        mock_client.containers.get.side_effect = None
        mock_client.containers.get.return_value = container

        target = DockerImageTarget(image="my-image:latest")
        assert target.status() == TargetStatus.RUNNING

    def test_status_stopped_no_container(self, mock_client: MagicMock) -> None:
        """Preconditions: No container exists (NotFound).
        Tests: status() returns TargetStatus.STOPPED.
        Success: Return value is TargetStatus.STOPPED.
        """
        target = DockerImageTarget(image="my-image:latest")
        assert target.status() == TargetStatus.STOPPED

    def test_status_exited(self, mock_client: MagicMock) -> None:
        """Preconditions: Container exists with status 'exited'.
        Tests: status() returns TargetStatus.STOPPED for exited containers.
        Success: Return value is TargetStatus.STOPPED.
        """
        container = MagicMock()
        container.status = "exited"
        mock_client.containers.get.side_effect = None
        mock_client.containers.get.return_value = container

        target = DockerImageTarget(image="my-image:latest")
        assert target.status() == TargetStatus.STOPPED

    def test_status_starting(self, mock_client: MagicMock) -> None:
        """Preconditions: Container exists with status 'created'.
        Tests: status() returns TargetStatus.STARTING.
        Success: Return value is TargetStatus.STARTING.
        """
        container = MagicMock()
        container.status = "created"
        mock_client.containers.get.side_effect = None
        mock_client.containers.get.return_value = container

        target = DockerImageTarget(image="my-image:latest")
        assert target.status() == TargetStatus.STARTING


# ---------------------------------------------------------------------------
# resolve_xml_path()
# ---------------------------------------------------------------------------


class TestResolveXmlPath:

    def test_resolve_xml_path(self, mock_client: MagicMock) -> None:
        """Preconditions: Host path is /tmp/output/patrol.xml.
        Tests: resolve_xml_path extracts filename and prefixes with /bt_xml/.
        Success: Returns '/bt_xml/patrol.xml'.
        """
        target = DockerImageTarget(image="my-image:latest")
        result = target.resolve_xml_path(Path("/tmp/output/patrol.xml"))
        assert result == "/bt_xml/patrol.xml"
