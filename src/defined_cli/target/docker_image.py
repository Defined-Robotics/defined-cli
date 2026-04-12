"""DockerImageTarget — manages a pre-built Docker image via docker-py.

Unlike SimTarget (which uses docker compose to build and run the full
simulation stack), this target runs a single pre-built image pulled
from a registry. Used when ``defined.yaml`` specifies ``sim.image``.

The container is named ``defined_sim`` and exposes rosbridge on the
configured port. Compiled BT XML files are shared via a bind mount
from the host output directory into ``/bt_xml`` in the container.
"""

from __future__ import annotations

import logging
from pathlib import Path

import docker
import docker.errors

from defined_cli.errors import BackendError
from defined_cli.target import TargetBase, TargetStatus

_log = logging.getLogger(__name__)

_CONTAINER_NAME = "defined_sim"
_CONTAINER_BT_XML_PATH = "/bt_xml"


class DockerImageTarget(TargetBase):
    """Backend target that runs a pre-built Docker image.

    Args:
        image: Docker image reference (e.g. ``ghcr.io/defined-robotics/sim:0.1.0``).
        bt_xml_dir: Host directory where compiled BT XML is written.
            Bind-mounted into the container at ``/bt_xml``.
        world_env: Gazebo world name passed as ``WORLD_NAME`` env var.
        port: Rosbridge port to expose (default 9090).
    """

    def __init__(
        self,
        image: str,
        *,
        bt_xml_dir: Path | None = None,
        world_env: str | None = None,
        port: int = 9090,
    ) -> None:
        self._image = image
        self._bt_xml_dir = bt_xml_dir
        self._world_env = world_env
        self._port = port
        self._client = _get_client()

    def start(self) -> None:
        """Pull image if needed, remove stale container, and start."""
        self._remove_existing()

        environment: dict[str, str] = {}
        if self._world_env:
            environment["WORLD_NAME"] = self._world_env

        volumes: dict[str, dict[str, str]] = {}
        if self._bt_xml_dir is not None:
            self._bt_xml_dir.mkdir(parents=True, exist_ok=True)
            volumes[str(self._bt_xml_dir)] = {
                "bind": _CONTAINER_BT_XML_PATH,
                "mode": "rw",
            }

        try:
            self._client.containers.run(
                self._image,
                name=_CONTAINER_NAME,
                detach=True,
                ports={"9090/tcp": self._port},
                volumes=volumes or None,
                environment=environment or None,
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

    def _remove_existing(self) -> None:
        """Remove a stale container if it exists."""
        try:
            container = self._client.containers.get(_CONTAINER_NAME)
            container.stop()
            container.remove()
        except docker.errors.NotFound:
            pass
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
