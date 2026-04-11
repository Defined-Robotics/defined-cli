"""Tests for defined.yaml project manifest discovery and loading.

Covers:
- Auto-discovery (walk up from cwd)
- Schema validation (full and minimal manifests)
- Path resolution relative to manifest directory
- Optional sim section
"""

from pathlib import Path

import pytest

from defined_cli.manifest import (
    ManifestNotFoundError,
    ProjectManifest,
    discover_manifest,
    load_manifest,
)


# ---------------------------------------------------------------------------
# Manifest discovery
# ---------------------------------------------------------------------------


def test_discover_walks_up_to_find_manifest(tmp_path: Path) -> None:
    """discover_manifest walks up from a subdirectory to find defined.yaml."""
    manifest_file = tmp_path / "defined.yaml"
    manifest_file.write_text("project:\n  name: test\nrobot:\n  rdf: robot.rdf.yaml\n")
    nested = tmp_path / "tasks" / "subtasks"
    nested.mkdir(parents=True)

    result = discover_manifest(start=nested)
    assert result == manifest_file


def test_discover_finds_in_current_dir(tmp_path: Path) -> None:
    """discover_manifest finds defined.yaml in the start directory itself."""
    manifest_file = tmp_path / "defined.yaml"
    manifest_file.write_text("project:\n  name: test\nrobot:\n  rdf: robot.rdf.yaml\n")

    result = discover_manifest(start=tmp_path)
    assert result == manifest_file


def test_discover_raises_when_no_manifest(tmp_path: Path) -> None:
    """discover_manifest raises ManifestNotFoundError when nothing found."""
    nested = tmp_path / "deep" / "nested"
    nested.mkdir(parents=True)

    with pytest.raises(ManifestNotFoundError):
        discover_manifest(start=nested)


# ---------------------------------------------------------------------------
# Manifest loading — minimal
# ---------------------------------------------------------------------------


def test_load_minimal_manifest(tmp_path: Path) -> None:
    """A manifest with only project + robot sections is valid."""
    manifest_file = tmp_path / "defined.yaml"
    manifest_file.write_text(
        "project:\n"
        "  name: my-robot\n"
        "robot:\n"
        "  rdf: robot.rdf.yaml\n"
    )
    manifest = load_manifest(manifest_file)

    assert manifest.project.name == "my-robot"
    assert manifest.robot.rdf == tmp_path / "robot.rdf.yaml"
    assert manifest.sim is None
    assert manifest.world is None
    assert manifest.verbs is None


# ---------------------------------------------------------------------------
# Manifest loading — full
# ---------------------------------------------------------------------------


def test_load_full_manifest(tmp_path: Path) -> None:
    """A manifest with all sections parses correctly."""
    manifest_file = tmp_path / "defined.yaml"
    manifest_file.write_text(
        "project:\n"
        "  name: my-robot\n"
        "  cli_version: '>=0.1.0'\n"
        "robot:\n"
        "  rdf: robots/burger.rdf.yaml\n"
        "world:\n"
        "  file: worlds/maze.yaml\n"
        "verbs:\n"
        "  path: verbs/\n"
        "sim:\n"
        "  image: ghcr.io/defined-robotics/sim:0.1.0\n"
    )
    manifest = load_manifest(manifest_file)

    assert manifest.project.name == "my-robot"
    assert manifest.project.cli_version == ">=0.1.0"
    assert manifest.robot.rdf == tmp_path / "robots" / "burger.rdf.yaml"
    assert manifest.world.file == tmp_path / "worlds" / "maze.yaml"
    assert manifest.verbs.path == tmp_path / "verbs"
    assert manifest.sim.image == "ghcr.io/defined-robotics/sim:0.1.0"


# ---------------------------------------------------------------------------
# Path resolution
# ---------------------------------------------------------------------------


def test_paths_resolved_relative_to_manifest_dir(tmp_path: Path) -> None:
    """Relative paths in the manifest are resolved against the manifest's directory."""
    subdir = tmp_path / "project"
    subdir.mkdir()
    manifest_file = subdir / "defined.yaml"
    manifest_file.write_text(
        "project:\n"
        "  name: test\n"
        "robot:\n"
        "  rdf: ../shared/robot.rdf.yaml\n"
    )
    manifest = load_manifest(manifest_file)

    assert manifest.robot.rdf == (subdir / ".." / "shared" / "robot.rdf.yaml").resolve()


# ---------------------------------------------------------------------------
# Optional sections
# ---------------------------------------------------------------------------


def test_sim_section_optional(tmp_path: Path) -> None:
    """Hardware users omit the sim section."""
    manifest_file = tmp_path / "defined.yaml"
    manifest_file.write_text(
        "project:\n"
        "  name: hw-robot\n"
        "robot:\n"
        "  rdf: robot.rdf.yaml\n"
    )
    manifest = load_manifest(manifest_file)
    assert manifest.sim is None


def test_world_section_optional(tmp_path: Path) -> None:
    """World section is optional (user may manage POIs via CLI)."""
    manifest_file = tmp_path / "defined.yaml"
    manifest_file.write_text(
        "project:\n"
        "  name: test\n"
        "robot:\n"
        "  rdf: robot.rdf.yaml\n"
    )
    manifest = load_manifest(manifest_file)
    assert manifest.world is None


def test_verbs_section_optional(tmp_path: Path) -> None:
    """Verbs section is optional (defaults to built-in verbs only)."""
    manifest_file = tmp_path / "defined.yaml"
    manifest_file.write_text(
        "project:\n"
        "  name: test\n"
        "robot:\n"
        "  rdf: robot.rdf.yaml\n"
    )
    manifest = load_manifest(manifest_file)
    assert manifest.verbs is None
