"""Project manifest (defined.yaml) schema and loading.

The manifest is the entry point for a Defined Robotics project. It tells
the CLI where to find the robot definition, world file, verb overrides,
and simulation image.

The manifest path must be provided explicitly — there is no
auto-discovery or directory walk-up.

This module has zero CLI-specific imports (no click, rich, textual)
so it can be used from ``state/`` and ``mission/`` layers.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, ValidationError


# ---------------------------------------------------------------------------
# Exceptions (plain Python — no click dependency)
# ---------------------------------------------------------------------------


class ManifestNotFoundError(FileNotFoundError):
    """Raised when the specified manifest file does not exist."""


class ManifestValidationError(ValueError):
    """Raised when the manifest file exists but is invalid."""


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
# Loading
# ---------------------------------------------------------------------------


_MANIFEST_FILENAME = "defined.yaml"


def load_manifest(path: Path) -> ProjectManifest:
    """Load and validate a project manifest.

    Relative paths in the manifest are resolved against the
    manifest file's parent directory.

    Args:
        path: Path to the defined.yaml file.

    Returns:
        Validated ProjectManifest with absolute paths.

    Raises:
        ManifestNotFoundError: If the file does not exist.
        ManifestValidationError: If the file is malformed or fails validation.
    """
    if not path.is_file():
        raise ManifestNotFoundError(f"Manifest not found: {path}")

    try:
        raw = yaml.safe_load(path.read_text())
    except yaml.YAMLError as exc:
        raise ManifestValidationError(
            f"Manifest is not valid YAML: {path}\n{exc}"
        ) from exc

    if raw is None or not isinstance(raw, dict):
        raise ManifestValidationError(
            f"Manifest is empty or not a YAML mapping: {path}"
        )

    try:
        manifest = ProjectManifest.model_validate(raw)
    except ValidationError as exc:
        raise ManifestValidationError(
            f"Manifest validation failed: {path}\n{exc}"
        ) from exc

    manifest_dir = path.parent.resolve()

    # Resolve relative paths against the manifest directory
    manifest.robot.rdf = (manifest_dir / manifest.robot.rdf).resolve()

    if manifest.world is not None:
        manifest.world.file = (manifest_dir / manifest.world.file).resolve()

    if manifest.verbs is not None:
        manifest.verbs.path = (manifest_dir / manifest.verbs.path).resolve()

    return manifest
