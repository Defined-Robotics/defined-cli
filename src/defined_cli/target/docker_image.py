"""DockerImageTarget — manages a pre-built Docker image via docker run.

Unlike SimTarget (which uses docker compose to build and run the full
simulation stack), this target runs a single pre-built image pulled
from a registry. Used when ``defined.yaml`` specifies ``sim.image``.

The container is named ``defined_sim`` and exposes rosbridge on the
configured port. BT XML files are shared via a Docker volume.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from defined_cli.errors import BackendError
from defined_cli.target import TargetBase, TargetStatus

_CONTAINER_NAME = "defined_sim"
_VOLUME_NAME = "defined_bt_xml"


class DockerImageTarget(TargetBase):
    """Backend target that runs a pre-built Docker image.

    Args:
        image: Docker image reference (e.g. ``ghcr.io/defined-robotics/sim:0.1.0``).
        world_env: Gazebo world name passed as ``WORLD_NAME`` env var.
        port: Rosbridge port to expose (default 9090).
    """

    def __init__(
        self,
        image: str,
        *,
        world_env: str | None = None,
        port: int = 9090,
    ) -> None:
        self._image = image
        self._world_env = world_env
        self._port = port

    def start(self) -> None:
        """Pull image if needed, remove stale container, and start."""
        # Remove any existing container (ignore errors if it doesn't exist)
        self._docker("rm", "-f", _CONTAINER_NAME, allow_failure=True)

        cmd = [
            "docker", "run", "-d",
            "--name", _CONTAINER_NAME,
            "-p", f"{self._port}:9090",
            "-v", f"{_VOLUME_NAME}:/bt_xml",
        ]

        if self._world_env:
            cmd.extend(["-e", f"WORLD_NAME={self._world_env}"])

        cmd.append(self._image)
        self._docker(*cmd[1:])  # skip "docker" prefix — _docker adds it

    def stop(self) -> None:
        """Stop and remove the container."""
        self._docker("stop", _CONTAINER_NAME, allow_failure=True)
        self._docker("rm", "-f", _CONTAINER_NAME, allow_failure=True)

    def status(self) -> TargetStatus:
        """Query container state via docker inspect."""
        try:
            result = self._docker("inspect", _CONTAINER_NAME, capture=True)
        except BackendError:
            return TargetStatus.STOPPED

        try:
            data = json.loads(result.stdout)
            # docker inspect returns a list; we get the first element
            if isinstance(data, list):
                data = data[0]
            state = data.get("State", {}).get("Status", "").lower()
            if state == "running":
                return TargetStatus.RUNNING
            if state in ("created", "restarting"):
                return TargetStatus.STARTING
            return TargetStatus.STOPPED
        except (json.JSONDecodeError, KeyError, IndexError):
            return TargetStatus.ERROR

    def resolve_xml_path(self, host_path: Path) -> str:
        """Translate host path to container path via shared volume."""
        return f"/bt_xml/{host_path.name}"

    # -- internals --

    def _docker(
        self,
        *args: str,
        capture: bool = False,
        allow_failure: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        cmd = ["docker", *args]
        try:
            return subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=not allow_failure,
            )
        except FileNotFoundError as exc:
            raise BackendError(
                "Docker is not installed",
                suggestion="Install Docker Desktop: https://docs.docker.com/get-docker/",
                detail=str(exc),
            ) from exc
        except subprocess.CalledProcessError as exc:
            raise BackendError(
                "docker command failed",
                suggestion="Is Docker running? Try: docker info",
                detail=exc.stderr or str(exc),
            ) from exc
