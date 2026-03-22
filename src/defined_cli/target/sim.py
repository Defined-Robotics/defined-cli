"""SimTarget — manages the simulation stack via docker compose."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from defined_cli.errors import BackendError
from defined_cli.target import TargetBase, TargetStatus

# Default compose file relative to the repo root.
_DEFAULT_COMPOSE = Path("work/defined_platform/docker/docker-compose.yml")


class SimTarget(TargetBase):
    """Backend target that manages the Docker-based simulation stack.

    Args:
        compose_file: Path to docker-compose.yml. If ``None``, searches
            upward from CWD for the default compose file.

    Raises:
        BackendError: If the compose file cannot be found.
    """

    def __init__(self, compose_file: Path | None = None) -> None:
        self._compose_file = compose_file or self._find_compose_file()

    def start(self) -> None:
        self._compose("up", "-d")

    def stop(self) -> None:
        self._compose("down")

    def status(self) -> TargetStatus:
        result = self._compose("ps", "--format", "json", capture=True)
        if not result.stdout.strip():
            return TargetStatus.STOPPED
        try:
            # docker compose ps --format json outputs one JSON object per line
            for line in result.stdout.strip().splitlines():
                container = json.loads(line)
                state = container.get("State", "").lower()
                if state == "running":
                    return TargetStatus.RUNNING
                if state in ("created", "restarting"):
                    return TargetStatus.STARTING
            return TargetStatus.STOPPED
        except (json.JSONDecodeError, KeyError):
            return TargetStatus.ERROR

    def resolve_xml_path(self, host_path: Path) -> str:
        return f"/bt_xml/{host_path.name}"

    # -- internals --

    def _compose(
        self, *args: str, capture: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        cmd = ["docker", "compose", "-f", str(self._compose_file), *args]
        try:
            return subprocess.run(
                cmd,
                capture_output=capture,
                text=True,
                check=not capture,
            )
        except FileNotFoundError as exc:
            raise BackendError(
                "Docker is not installed",
                suggestion="Install Docker Desktop: https://docs.docker.com/get-docker/",
                detail=str(exc),
            ) from exc
        except subprocess.CalledProcessError as exc:
            raise BackendError(
                "docker compose command failed",
                suggestion="Is Docker running? Try: docker info",
                detail=exc.stderr or str(exc),
            ) from exc

    @staticmethod
    def _find_compose_file() -> Path:
        # Walk up from CWD looking for the compose file
        cwd = Path.cwd()
        for parent in [cwd, *cwd.parents]:
            candidate = parent / _DEFAULT_COMPOSE
            if candidate.exists():
                return candidate
        raise BackendError(
            "Cannot find docker-compose.yml",
            suggestion=f"Run from the repo root, or pass --compose-file",
            detail=f"Searched for {_DEFAULT_COMPOSE} from {cwd}",
        )
