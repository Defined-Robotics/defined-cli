"""Project manifest (defined.yaml) schema and discovery.

The manifest is the entry point for a Defined Robotics project. It tells
the CLI where to find the robot definition, world file, verb overrides,
and simulation image.

Auto-discovery walks up from cwd looking for ``defined.yaml``, similar
to how npm finds ``package.json``.

This module has zero CLI-specific imports (no click, rich, textual)
so it can be used from ``state/`` and ``mission/`` layers.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel


# ---------------------------------------------------------------------------
# Exceptions (plain Python — no click dependency)
# ---------------------------------------------------------------------------


class ManifestNotFoundError(FileNotFoundError):
    """Raised when no defined.yaml is found walking up from cwd."""


# ---------------------------------------------------------------------------
# Schema sections
# ---------------------------------------------------------------------------


class ProjectSection(BaseModel):
    """Top-level project metadata."""

    name: str
    cli_version: str = ""


class RobotSection(BaseModel):
    """Robot definition reference."""

    rdf: Path


class WorldSection(BaseModel):
    """World definition reference."""

    file: Path


class VerbsSection(BaseModel):
    """Verb overrides directory."""

    path: Path


class SimSection(BaseModel):
    """Simulation configuration (omitted for hardware targets)."""

    image: str


# ---------------------------------------------------------------------------
# Full manifest
# ---------------------------------------------------------------------------


class ProjectManifest(BaseModel):
    """Complete project manifest from defined.yaml."""

    project: ProjectSection
    robot: RobotSection
    world: WorldSection | None = None
    verbs: VerbsSection | None = None
    sim: SimSection | None = None


# ---------------------------------------------------------------------------
# Discovery and loading
# ---------------------------------------------------------------------------


_MANIFEST_FILENAME = "defined.yaml"


def discover_manifest(start: Path | None = None) -> Path:
    """Walk up from *start* looking for defined.yaml.

    Args:
        start: Directory to start searching from. Defaults to cwd.

    Returns:
        Absolute path to the manifest file.

    Raises:
        ManifestNotFoundError: If no manifest is found.
    """
    current = (start or Path.cwd()).resolve()
    for directory in [current, *current.parents]:
        candidate = directory / _MANIFEST_FILENAME
        if candidate.is_file():
            return candidate
    raise ManifestNotFoundError(
        f"No {_MANIFEST_FILENAME} found searching upward from {current}"
    )


def load_manifest(path: Path) -> ProjectManifest:
    """Load and validate a project manifest.

    Relative paths in the manifest are resolved against the
    manifest file's parent directory.

    Args:
        path: Path to the defined.yaml file.

    Returns:
        Validated ProjectManifest with absolute paths.
    """
    raw = yaml.safe_load(path.read_text())
    manifest = ProjectManifest.model_validate(raw)
    manifest_dir = path.parent.resolve()

    # Resolve relative paths against the manifest directory
    manifest.robot.rdf = (manifest_dir / manifest.robot.rdf).resolve()

    if manifest.world is not None:
        manifest.world.file = (manifest_dir / manifest.world.file).resolve()

    if manifest.verbs is not None:
        manifest.verbs.path = (manifest_dir / manifest.verbs.path).resolve()

    return manifest
