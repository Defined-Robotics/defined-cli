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

from defined_rdf.robot_config import DriveConfig, RobotConfig

from defined_cli.errors import BackendError
from defined_cli.target import TargetStatus
from defined_cli.target.docker_image import (
    DockerImageTarget,
    _compute_config_hash,
    _CONFIG_HASH_LABEL,
    robot_config_to_sim_env,
)


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
        assert call_kwargs[1]["ports"] == {
            "9090/tcp": ("127.0.0.1", 9090),
            "8765/tcp": ("127.0.0.1", 8765),
        }

    def test_start_passes_world_env(self, mock_client: MagicMock) -> None:
        """Preconditions: world_env is set to 'warehouse'.
        Tests: start() passes WORLD_NAME as environment variable.
        Success: containers.run receives environment containing WORLD_NAME.
        """
        target = DockerImageTarget(image="my-image:latest", world_env="warehouse")
        target.start()

        call_kwargs = mock_client.containers.run.call_args[1]
        assert call_kwargs["environment"]["WORLD_NAME"] == "warehouse"

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

    def test_start_removes_existing_container_with_different_hash(self, mock_client: MagicMock) -> None:
        """Preconditions: A stale container with a different config hash exists.
        Tests: start() stops and removes it before creating a new one.
        Success: container.stop() and container.remove() called before containers.run().
        """
        stale = MagicMock()
        stale.labels = {_CONFIG_HASH_LABEL: "old_hash_value"}
        stale.status = "running"
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


# ---------------------------------------------------------------------------
# robot_config_to_sim_env()
# ---------------------------------------------------------------------------

def _make_drive(**overrides: float) -> DriveConfig:
    defaults = dict(
        wheel_separation=0.160,
        wheel_radius=0.033,
        max_linear_velocity=0.22,
        max_angular_velocity=2.84,
    )
    defaults.update(overrides)
    return DriveConfig(**defaults)


class TestRobotConfigToSimEnv:

    def test_drive_only(self) -> None:
        """Minimal robot — drive params, no sensors."""
        config = RobotConfig(name="minimal", drive=_make_drive(), sensors={})
        env = robot_config_to_sim_env(config)

        assert env["ROBOT_WHEEL_SEPARATION"] == "0.16"
        assert env["ROBOT_WHEEL_RADIUS"] == "0.033"
        assert env["ROBOT_MAX_LINEAR_VEL"] == "0.22"
        assert env["ROBOT_MAX_ANGULAR_VEL"] == "2.84"
        assert env["ROBOT_HAS_LIDAR"] == "false"
        assert env["ROBOT_HAS_CAMERA"] == "false"

    def test_with_lidar(self) -> None:
        """Robot with lidar — lidar env vars populated."""
        config = RobotConfig(
            name="burger",
            drive=_make_drive(),
            sensors={
                "lidar_2d": {
                    "range_min": 0.120,
                    "range_max": 3.500,
                    "samples": 360,
                    "update_rate": 5.0,
                },
            },
        )
        env = robot_config_to_sim_env(config)

        assert env["ROBOT_HAS_LIDAR"] == "true"
        assert env["ROBOT_LIDAR_RANGE_MIN"] == "0.12"
        assert env["ROBOT_LIDAR_RANGE_MAX"] == "3.5"
        assert env["ROBOT_LIDAR_SAMPLES"] == "360"
        assert env["ROBOT_LIDAR_UPDATE_RATE"] == "5.0"
        assert env["ROBOT_HAS_CAMERA"] == "false"

    def test_with_camera(self) -> None:
        """Robot with camera — camera env vars populated."""
        config = RobotConfig(
            name="burger_cam",
            drive=_make_drive(),
            sensors={
                "rgb_camera": {
                    "resolution_width": 640,
                    "resolution_height": 480,
                    "fps": 30,
                },
            },
        )
        env = robot_config_to_sim_env(config)

        assert env["ROBOT_HAS_CAMERA"] == "true"
        assert env["ROBOT_CAMERA_WIDTH"] == "640"
        assert env["ROBOT_CAMERA_HEIGHT"] == "480"
        assert env["ROBOT_CAMERA_FPS"] == "30"

    def test_full_robot(self) -> None:
        """Robot with both lidar + camera — all env vars present."""
        config = RobotConfig(
            name="full",
            drive=_make_drive(wheel_separation=0.287, wheel_radius=0.05),
            sensors={
                "lidar_2d": {"range_min": 0.1, "range_max": 12.0, "samples": 720, "update_rate": 20.0},
                "rgb_camera": {"resolution_width": 1280, "resolution_height": 720, "fps": 60},
            },
        )
        env = robot_config_to_sim_env(config)

        assert env["ROBOT_WHEEL_SEPARATION"] == "0.287"
        assert env["ROBOT_WHEEL_RADIUS"] == "0.05"
        assert env["ROBOT_HAS_LIDAR"] == "true"
        assert env["ROBOT_LIDAR_SAMPLES"] == "720"
        assert env["ROBOT_HAS_CAMERA"] == "true"
        assert env["ROBOT_CAMERA_WIDTH"] == "1280"

    def test_unknown_sensor_ignored(self) -> None:
        """Unknown sensor types should not produce env vars (they're not sim-mappable)."""
        config = RobotConfig(
            name="custom",
            drive=_make_drive(),
            sensors={"gps": {"accuracy": 2.5}},
        )
        env = robot_config_to_sim_env(config)

        # GPS has no sim env mapping — should not appear
        assert not any("GPS" in k for k in env)
        # Drive params still present
        assert "ROBOT_WHEEL_SEPARATION" in env

    def test_all_values_are_strings(self) -> None:
        """Docker env vars must all be strings."""
        config = RobotConfig(
            name="test",
            drive=_make_drive(),
            sensors={"lidar_2d": {"range_min": 0.12, "range_max": 3.5, "samples": 360, "update_rate": 5.0}},
        )
        env = robot_config_to_sim_env(config)
        for k, v in env.items():
            assert isinstance(v, str), f"{k}={v!r} is not a string"


class TestDockerImageTargetRobotConfig:

    def test_start_passes_robot_env(self, mock_client: MagicMock) -> None:
        """DockerImageTarget merges robot config env vars into container environment."""
        config = RobotConfig(
            name="test",
            drive=_make_drive(),
            sensors={"rgb_camera": {"resolution_width": 640, "resolution_height": 480, "fps": 30}},
        )
        target = DockerImageTarget(
            image="my-image:latest",
            robot_config=config,
        )
        target.start()

        call_kwargs = mock_client.containers.run.call_args[1]
        env = call_kwargs["environment"]
        assert env["ROBOT_HAS_CAMERA"] == "true"
        assert env["ROBOT_WHEEL_SEPARATION"] == "0.16"

    def test_start_merges_world_and_robot_env(self, mock_client: MagicMock) -> None:
        """Both WORLD_NAME and ROBOT_* env vars should be present."""
        config = RobotConfig(name="test", drive=_make_drive(), sensors={})
        target = DockerImageTarget(
            image="my-image:latest",
            world_env="maze",
            robot_config=config,
        )
        target.start()

        call_kwargs = mock_client.containers.run.call_args[1]
        env = call_kwargs["environment"]
        assert env["WORLD_NAME"] == "maze"
        assert "ROBOT_WHEEL_SEPARATION" in env


# ---------------------------------------------------------------------------
# _compute_config_hash()
# ---------------------------------------------------------------------------


class TestComputeConfigHash:

    def test_deterministic(self) -> None:
        """Same inputs always produce the same hash."""
        h1 = _compute_config_hash("img:1", "cmd", {"A": "1"})
        h2 = _compute_config_hash("img:1", "cmd", {"A": "1"})
        assert h1 == h2

    def test_different_image_different_hash(self) -> None:
        """Changing the image changes the hash."""
        h1 = _compute_config_hash("img:1", "cmd", {})
        h2 = _compute_config_hash("img:2", "cmd", {})
        assert h1 != h2

    def test_different_env_different_hash(self) -> None:
        """Changing env vars changes the hash."""
        h1 = _compute_config_hash("img:1", "cmd", {"WORLD_NAME": "maze"})
        h2 = _compute_config_hash("img:1", "cmd", {"WORLD_NAME": "room"})
        assert h1 != h2

    def test_different_command_different_hash(self) -> None:
        """Changing the command (e.g. spawn pose) changes the hash."""
        h1 = _compute_config_hash("img:1", "cmd x:=0 y:=0", {})
        h2 = _compute_config_hash("img:1", "cmd x:=1 y:=2", {})
        assert h1 != h2

    def test_hash_length(self) -> None:
        """Hash is 12 hex characters."""
        h = _compute_config_hash("img:1", "cmd", {})
        assert len(h) == 12
        assert all(c in "0123456789abcdef" for c in h)

    def test_env_key_order_irrelevant(self) -> None:
        """Dict ordering doesn't affect the hash (sort_keys=True)."""
        h1 = _compute_config_hash("img:1", "cmd", {"A": "1", "B": "2"})
        h2 = _compute_config_hash("img:1", "cmd", {"B": "2", "A": "1"})
        assert h1 == h2


# ---------------------------------------------------------------------------
# Config-hash container lifecycle
# ---------------------------------------------------------------------------


class TestConfigHashLifecycle:

    def test_reuse_running_container_with_same_hash(self, mock_client: MagicMock) -> None:
        """Container with matching hash and running — skip recreation."""
        target = DockerImageTarget(image="my-image:latest")
        command, env, _ = target._build_run_args()
        expected_hash = _compute_config_hash("my-image:latest", command, env)

        existing = MagicMock()
        existing.labels = {_CONFIG_HASH_LABEL: expected_hash}
        existing.status = "running"
        mock_client.containers.get.side_effect = None
        mock_client.containers.get.return_value = existing

        target.start()

        # Should NOT create a new container
        mock_client.containers.run.assert_not_called()
        # Should NOT stop the existing one
        existing.stop.assert_not_called()

    def test_restart_stopped_container_with_same_hash(self, mock_client: MagicMock) -> None:
        """Container with matching hash but stopped — restart it."""
        target = DockerImageTarget(image="my-image:latest")
        command, env, _ = target._build_run_args()
        expected_hash = _compute_config_hash("my-image:latest", command, env)

        existing = MagicMock()
        existing.labels = {_CONFIG_HASH_LABEL: expected_hash}
        existing.status = "exited"
        mock_client.containers.get.side_effect = None
        mock_client.containers.get.return_value = existing

        target.start()

        # Should restart, not recreate
        existing.start.assert_called_once()
        mock_client.containers.run.assert_not_called()

    def test_rebuild_on_hash_mismatch(self, mock_client: MagicMock) -> None:
        """Container with different hash — tear down and rebuild."""
        existing = MagicMock()
        existing.labels = {_CONFIG_HASH_LABEL: "stale_hash_00"}
        existing.status = "running"
        mock_client.containers.get.side_effect = None
        mock_client.containers.get.return_value = existing

        target = DockerImageTarget(image="my-image:latest")
        target.start()

        existing.stop.assert_called_once()
        existing.remove.assert_called_once()
        mock_client.containers.run.assert_called_once()

    def test_rebuild_when_no_hash_label(self, mock_client: MagicMock) -> None:
        """Existing container without the hash label — treat as stale, rebuild."""
        existing = MagicMock()
        existing.labels = {}
        existing.status = "running"
        mock_client.containers.get.side_effect = None
        mock_client.containers.get.return_value = existing

        target = DockerImageTarget(image="my-image:latest")
        target.start()

        existing.stop.assert_called_once()
        existing.remove.assert_called_once()
        mock_client.containers.run.assert_called_once()

    def test_fresh_start_no_existing_container(self, mock_client: MagicMock) -> None:
        """No existing container — create new one with hash label."""
        target = DockerImageTarget(image="my-image:latest")
        target.start()

        call_kwargs = mock_client.containers.run.call_args[1]
        assert _CONFIG_HASH_LABEL in call_kwargs["labels"]
        assert len(call_kwargs["labels"][_CONFIG_HASH_LABEL]) == 12

    def test_config_change_detected_across_robots(self, mock_client: MagicMock) -> None:
        """Switching from burger to burger_cam produces different hash."""
        burger = RobotConfig(name="burger", drive=_make_drive(), sensors={})
        burger_cam = RobotConfig(
            name="burger_cam",
            drive=_make_drive(),
            sensors={"rgb_camera": {"resolution_width": 640, "resolution_height": 480, "fps": 30}},
        )

        t1 = DockerImageTarget(image="img:1", robot_config=burger)
        t2 = DockerImageTarget(image="img:1", robot_config=burger_cam)

        cmd1, env1, _ = t1._build_run_args()
        cmd2, env2, _ = t2._build_run_args()

        h1 = _compute_config_hash("img:1", cmd1, env1)
        h2 = _compute_config_hash("img:1", cmd2, env2)
        assert h1 != h2
