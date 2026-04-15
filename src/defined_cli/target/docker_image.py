"""DockerImageTarget — manages a pre-built Docker image via docker-py.

Unlike SimTarget (which uses docker compose to build and run the full
simulation stack), this target runs a single pre-built image pulled
from a registry. Used when ``defined.yaml`` specifies ``sim.image``.

The container is named ``defined_sim`` and exposes rosbridge on the
configured port. Compiled BT XML files are shared via a bind mount
from the host output directory into ``/bt_xml`` in the container.
"""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path

import docker
import docker.errors

from defined_rdf.robot_config import RobotConfig

from defined_cli.errors import BackendError
from defined_cli.target import TargetBase, TargetStatus

_log = logging.getLogger(__name__)

_CONTAINER_NAME = "defined_sim"
_CONTAINER_BT_XML_PATH = "/bt_xml"
_CONFIG_HASH_LABEL = "defined.config_hash"

# Base command to launch the full simulation stack inside the container.
# The image's own CMD is just "bash" (interactive use), so we must override.
# Spawn position args (x, y, yaw) are appended at runtime from world config.
_BASE_COMMAND = (
    "ros2 launch defined_bringup simulation.launch.py"
    " use_gui:=false use_slam:=true run_bt:=true run_explore:=true"
)

# ---------------------------------------------------------------------------
# Sensor env-var registry — extensible: add one dict entry per new sensor.
# Keys starting with "__present__" become "true" when the capability exists.
# Other values are looked up in the sensor's parameter dict.
# ---------------------------------------------------------------------------

_PRESENT = "__present__"

_SENSOR_ENV_REGISTRY: dict[str, dict[str, str]] = {
    "lidar_2d": {
        "ROBOT_HAS_LIDAR": _PRESENT,
        "ROBOT_LIDAR_RANGE_MIN": "range_min",
        "ROBOT_LIDAR_RANGE_MAX": "range_max",
        "ROBOT_LIDAR_SAMPLES": "samples",
        "ROBOT_LIDAR_UPDATE_RATE": "update_rate",
    },
    "rgb_camera": {
        "ROBOT_HAS_CAMERA": _PRESENT,
        "ROBOT_CAMERA_WIDTH": "resolution_width",
        "ROBOT_CAMERA_HEIGHT": "resolution_height",
        "ROBOT_CAMERA_FPS": "fps",
    },
}


def robot_config_to_sim_env(config: RobotConfig) -> dict[str, str]:
    """Convert a RobotConfig to Docker environment variables.

    Drive parameters are always emitted.  Sensor parameters are emitted
    for sensor types that have entries in ``_SENSOR_ENV_REGISTRY``.
    Unknown sensor types are silently skipped (they have no sim mapping).
    """
    env: dict[str, str] = {
        "ROBOT_WHEEL_SEPARATION": str(config.drive.wheel_separation),
        "ROBOT_WHEEL_RADIUS": str(config.drive.wheel_radius),
        "ROBOT_MAX_LINEAR_VEL": str(config.drive.max_linear_velocity),
        "ROBOT_MAX_ANGULAR_VEL": str(config.drive.max_angular_velocity),
    }

    for sensor_type, mapping in _SENSOR_ENV_REGISTRY.items():
        has_key = next((k for k, v in mapping.items() if v == _PRESENT), None)
        if config.has_sensor(sensor_type):
            params = config.sensor_params(sensor_type)
            for env_key, param_key in mapping.items():
                if param_key == _PRESENT:
                    env[env_key] = "true"
                else:
                    env[env_key] = str(params[param_key])
        elif has_key:
            env[has_key] = "false"

    return env


def _compute_config_hash(
    image: str,
    command: str,
    environment: dict[str, str],
) -> str:
    """Compute a deterministic hash of all inputs that affect the container.

    Returns a 12-character hex digest.
    """
    blob = json.dumps(
        {"image": image, "command": command, "env": environment},
        sort_keys=True,
    )
    return hashlib.sha256(blob.encode()).hexdigest()[:12]


class DockerImageTarget(TargetBase):
    """Backend target that runs a pre-built Docker image.

    Args:
        image: Docker image reference (e.g. ``ghcr.io/defined-robotics/sim:0.1.0``).
        bt_xml_dir: Host directory where compiled BT XML is written.
            Bind-mounted into the container at ``/bt_xml``.
        world_env: Gazebo world name passed as ``WORLD_NAME`` env var.
        spawn: Robot spawn pose ``(x, y, yaw)`` passed as launch args.
        port: Rosbridge port to expose (default 9090).
        robot_config: Optional RobotConfig to translate into ``ROBOT_*`` env vars.
    """

    def __init__(
        self,
        image: str,
        *,
        bt_xml_dir: Path | None = None,
        world_env: str | None = None,
        spawn: tuple[float, float, float] | None = None,
        port: int = 9090,
        robot_config: RobotConfig | None = None,
    ) -> None:
        self._image = image
        self._bt_xml_dir = bt_xml_dir
        self._world_env = world_env
        self._spawn = spawn
        self._port = port
        self._robot_config = robot_config
        self._client = _get_client()

    def _build_run_args(self) -> tuple[str, dict[str, str], dict[str, dict[str, str]]]:
        """Build the command, environment, and volumes for container creation."""
        command = _BASE_COMMAND
        if self._spawn is not None:
            x, y, yaw = self._spawn
            command += f" x:={x} y:={y} yaw:={yaw}"

        environment: dict[str, str] = {}
        if self._robot_config is not None:
            environment.update(robot_config_to_sim_env(self._robot_config))
        if self._world_env:
            environment["WORLD_NAME"] = self._world_env

        volumes: dict[str, dict[str, str]] = {}
        if self._bt_xml_dir is not None:
            self._bt_xml_dir.mkdir(parents=True, exist_ok=True)
            volumes[str(self._bt_xml_dir)] = {
                "bind": _CONTAINER_BT_XML_PATH,
                "mode": "rw",
            }

        return command, environment, volumes

    def start(self) -> None:
        """Start the sim container, reusing it if config hasn't changed.

        Computes a hash of all config inputs (image, env vars, spawn).
        If a container already exists with the same hash, it is reused.
        If the hash differs, the old container is replaced.
        """
        command, environment, volumes = self._build_run_args()
        config_hash = _compute_config_hash(self._image, command, environment)

        # Check for existing container
        existing = self._get_existing()
        if existing is not None:
            existing_hash = existing.labels.get(_CONFIG_HASH_LABEL)
            if existing_hash == config_hash:
                if existing.status == "running":
                    _log.info("Container config unchanged, reusing %s", _CONTAINER_NAME)
                    return
                # Same config but stopped — restart it
                _log.info("Restarting stopped container %s (config unchanged)", _CONTAINER_NAME)
                existing.start()
                return
            # Config changed — tear down and rebuild
            _log.info(
                "Config changed (%s → %s), rebuilding container",
                existing_hash,
                config_hash,
            )
            self._remove_existing()

        try:
            self._client.containers.run(
                self._image,
                command=command,
                name=_CONTAINER_NAME,
                detach=True,
                ports={
                    "9090/tcp": ("127.0.0.1", self._port),
                    "8765/tcp": ("127.0.0.1", 8765),
                },
                volumes=volumes or None,
                environment=environment or None,
                labels={_CONFIG_HASH_LABEL: config_hash},
            )
            _log.info("Started container %s from %s", _CONTAINER_NAME, self._image)
        except docker.errors.ImageNotFound as exc:
            raise BackendError(
                f"Docker image not found: {self._image}",
                suggestion="Pull the image first: docker pull " + self._image,
                detail=str(exc),
            ) from exc
        except docker.errors.APIError as exc:
            raise BackendError(
                "Failed to start Docker container",
                suggestion="Is Docker running? Try: docker info",
                detail=str(exc),
            ) from exc

    def stop(self) -> None:
        """Stop and remove the container."""
        try:
            container = self._client.containers.get(_CONTAINER_NAME)
            container.stop()
            container.remove()
            _log.info("Stopped and removed container %s", _CONTAINER_NAME)
        except docker.errors.NotFound:
            pass  # Already gone
        except docker.errors.APIError as exc:
            _log.warning("Error stopping container: %s", exc)

    def status(self) -> TargetStatus:
        """Query container state via Docker API."""
        try:
            container = self._client.containers.get(_CONTAINER_NAME)
            state = container.status
            if state == "running":
                return TargetStatus.RUNNING
            if state in ("created", "restarting"):
                return TargetStatus.STARTING
            return TargetStatus.STOPPED
        except docker.errors.NotFound:
            return TargetStatus.STOPPED
        except docker.errors.APIError:
            return TargetStatus.ERROR

    def resolve_xml_path(self, host_path: Path) -> str:
        """Translate host path to container path via bind mount."""
        return f"{_CONTAINER_BT_XML_PATH}/{host_path.name}"

    # -- internals --

    def _get_existing(self):
        """Return the existing container, or None."""
        try:
            return self._client.containers.get(_CONTAINER_NAME)
        except docker.errors.NotFound:
            return None

    def _remove_existing(self) -> None:
        """Remove a stale container if it exists."""
        container = self._get_existing()
        if container is None:
            return
        try:
            container.stop()
            container.remove()
        except docker.errors.APIError as exc:
            _log.warning("Could not remove stale container: %s", exc)


def _get_client() -> docker.DockerClient:
    """Create a Docker client, raising BackendError on failure."""
    try:
        return docker.from_env()
    except docker.errors.DockerException as exc:
        raise BackendError(
            "Cannot connect to Docker",
            suggestion="Is Docker running? Try: docker info",
            detail=str(exc),
        ) from exc
