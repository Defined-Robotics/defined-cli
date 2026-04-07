"""State persistence -- atomic YAML read/write for robot state.

Manages the ``~/.defined/state.yaml`` file. Writes are atomic
(temp file + ``os.replace``) to prevent corruption from crashes
or concurrent access.

Usage:
    from defined_cli.state.store import StateStore

    store = StateStore()
    snapshot = store.load()
    snapshot.robot.current = RobotStatus.IDLE
    store.save(snapshot)
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import yaml

from .model import StateSnapshot

_DEFAULT_PATH = Path.home() / ".defined" / "state.yaml"


class StateStore:
    """Single writer for ``~/.defined/state.yaml``.

    Args:
        path: Override the default state file path (for testing).
    """

    def __init__(self, path: Path | None = None) -> None:
        self._path = path or _DEFAULT_PATH

    @property
    def path(self) -> Path:
        """Return the state file path."""
        return self._path

    def load(self) -> StateSnapshot:
        """Load state from disk.

        Returns:
            The persisted snapshot, or a default ``StateSnapshot``
            if the file does not exist.

        Raises:
            yaml.YAMLError: If the file contains invalid YAML.
        """
        if not self._path.exists():
            return StateSnapshot()

        raw = yaml.safe_load(self._path.read_text())
        if raw is None:
            return StateSnapshot()

        return StateSnapshot.from_dict(raw)

    def save(self, snapshot: StateSnapshot) -> None:
        """Write state to disk atomically.

        Creates parent directories if needed. Writes to a temporary
        file in the same directory, then atomically replaces the
        target via ``os.replace``.
        """
        self._path.parent.mkdir(parents=True, exist_ok=True)

        data = snapshot.to_dict()
        content = yaml.dump(data, default_flow_style=False, sort_keys=False)

        fd, tmp_path = tempfile.mkstemp(
            dir=self._path.parent, suffix=".tmp",
        )
        try:
            with os.fdopen(fd, "w") as f:
                f.write(content)
            os.replace(tmp_path, self._path)
        except BaseException:
            # Clean up temp file on failure.
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
            raise
