"""Tests for defined.yaml project manifest loading and validation.

Covers:
- Loading valid manifests (minimal and full)
- Path resolution relative to manifest directory
- Optional sections (sim, world, verbs)
- Error handling: missing file, invalid YAML, incomplete, logically invalid
"""

from pathlib import Path

import pytest

from defined_cli.manifest import (
    ManifestNotFoundError,
    ManifestValidationError,
    ProjectManifest,
    load_manifest,
)


# ---------------------------------------------------------------------------
# Loading — valid manifests
# ---------------------------------------------------------------------------


def test_load_minimal_manifest(tmp_path: Path) -> None:
    """Preconditions: defined.yaml exists with only project + robot sections.
    Tests: Minimal manifest (required fields only) loads successfully.
    Success: project.name and robot.rdf populated; optional sections are None.
    """
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


def test_load_full_manifest(tmp_path: Path) -> None:
    """Preconditions: defined.yaml exists with all sections populated.
    Tests: Full manifest (all optional + required sections) parses correctly.
    Success: Every field populated with expected values; paths resolved.
    """
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
    """Preconditions: Manifest in subdirectory with relative path using '..'.
    Tests: Relative paths resolve against the manifest file's parent directory.
    Success: robot.rdf is an absolute path pointing to the resolved location.
    """
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
    """Preconditions: Manifest without sim section (hardware user).
    Tests: sim section defaults to None when omitted.
    Success: manifest.sim is None.
    """
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
    """Preconditions: Manifest without world section.
    Tests: world section defaults to None when omitted.
    Success: manifest.world is None.
    """
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
    """Preconditions: Manifest without verbs section.
    Tests: verbs section defaults to None when omitted.
    Success: manifest.verbs is None.
    """
    manifest_file = tmp_path / "defined.yaml"
    manifest_file.write_text(
        "project:\n"
        "  name: test\n"
        "robot:\n"
        "  rdf: robot.rdf.yaml\n"
    )
    manifest = load_manifest(manifest_file)
    assert manifest.verbs is None


# ---------------------------------------------------------------------------
# Error handling — missing file
# ---------------------------------------------------------------------------


def test_load_nonexistent_file_raises(tmp_path: Path) -> None:
    """Preconditions: Path points to a file that does not exist.
    Tests: load_manifest raises ManifestNotFoundError for missing files.
    Success: ManifestNotFoundError raised with path in message.
    """
    with pytest.raises(ManifestNotFoundError, match="Manifest not found"):
        load_manifest(tmp_path / "does_not_exist.yaml")


# ---------------------------------------------------------------------------
# Error handling — invalid YAML
# ---------------------------------------------------------------------------


def test_load_invalid_yaml_raises(tmp_path: Path) -> None:
    """Preconditions: File exists but contains malformed YAML (bad indentation).
    Tests: load_manifest raises ManifestValidationError for unparseable YAML.
    Success: ManifestValidationError raised with 'not valid YAML' in message.
    """
    manifest_file = tmp_path / "defined.yaml"
    manifest_file.write_text("project:\n  name: test\n bad_indent: oops\n")
    with pytest.raises(ManifestValidationError, match="not valid YAML"):
        load_manifest(manifest_file)


def test_load_empty_file_raises(tmp_path: Path) -> None:
    """Preconditions: File exists but is empty.
    Tests: load_manifest raises ManifestValidationError for empty files.
    Success: ManifestValidationError raised with 'empty' in message.
    """
    manifest_file = tmp_path / "defined.yaml"
    manifest_file.write_text("")
    with pytest.raises(ManifestValidationError, match="empty"):
        load_manifest(manifest_file)


def test_load_yaml_list_raises(tmp_path: Path) -> None:
    """Preconditions: File contains valid YAML but is a list, not a mapping.
    Tests: load_manifest rejects non-mapping YAML documents.
    Success: ManifestValidationError raised with 'not a YAML mapping' in message.
    """
    manifest_file = tmp_path / "defined.yaml"
    manifest_file.write_text("- item1\n- item2\n")
    with pytest.raises(ManifestValidationError, match="not a YAML mapping"):
        load_manifest(manifest_file)


# ---------------------------------------------------------------------------
# Error handling — incomplete manifests
# ---------------------------------------------------------------------------


def test_load_missing_project_section_raises(tmp_path: Path) -> None:
    """Preconditions: Manifest has robot section but no project section.
    Tests: load_manifest rejects manifest missing required 'project' field.
    Success: ManifestValidationError raised.
    """
    manifest_file = tmp_path / "defined.yaml"
    manifest_file.write_text("robot:\n  rdf: robot.rdf.yaml\n")
    with pytest.raises(ManifestValidationError, match="validation failed"):
        load_manifest(manifest_file)


def test_load_missing_robot_section_raises(tmp_path: Path) -> None:
    """Preconditions: Manifest has project section but no robot section.
    Tests: load_manifest rejects manifest missing required 'robot' field.
    Success: ManifestValidationError raised.
    """
    manifest_file = tmp_path / "defined.yaml"
    manifest_file.write_text("project:\n  name: test\n")
    with pytest.raises(ManifestValidationError, match="validation failed"):
        load_manifest(manifest_file)


def test_load_missing_project_name_raises(tmp_path: Path) -> None:
    """Preconditions: Manifest has project section but name field is missing.
    Tests: load_manifest rejects manifest where required sub-field is absent.
    Success: ManifestValidationError raised.
    """
    manifest_file = tmp_path / "defined.yaml"
    manifest_file.write_text("project:\n  cli_version: '1.0'\nrobot:\n  rdf: r.yaml\n")
    with pytest.raises(ManifestValidationError, match="validation failed"):
        load_manifest(manifest_file)


def test_load_missing_robot_rdf_raises(tmp_path: Path) -> None:
    """Preconditions: Manifest has robot section but rdf field is missing.
    Tests: load_manifest rejects manifest where required sub-field is absent.
    Success: ManifestValidationError raised.
    """
    manifest_file = tmp_path / "defined.yaml"
    manifest_file.write_text("project:\n  name: test\nrobot:\n  something: else\n")
    with pytest.raises(ManifestValidationError, match="validation failed"):
        load_manifest(manifest_file)


# ---------------------------------------------------------------------------
# Error handling — logical errors
# ---------------------------------------------------------------------------


def test_load_sim_missing_image_raises(tmp_path: Path) -> None:
    """Preconditions: Manifest has sim section but image field is missing.
    Tests: load_manifest rejects sim section without required 'image' field.
    Success: ManifestValidationError raised.
    """
    manifest_file = tmp_path / "defined.yaml"
    manifest_file.write_text(
        "project:\n"
        "  name: test\n"
        "robot:\n"
        "  rdf: robot.rdf.yaml\n"
        "sim:\n"
        "  something: else\n"
    )
    with pytest.raises(ManifestValidationError, match="validation failed"):
        load_manifest(manifest_file)


def test_load_world_missing_file_raises(tmp_path: Path) -> None:
    """Preconditions: Manifest has world section but file field is missing.
    Tests: load_manifest rejects world section without required 'file' field.
    Success: ManifestValidationError raised.
    """
    manifest_file = tmp_path / "defined.yaml"
    manifest_file.write_text(
        "project:\n"
        "  name: test\n"
        "robot:\n"
        "  rdf: robot.rdf.yaml\n"
        "world:\n"
        "  environment: maze\n"
    )
    with pytest.raises(ManifestValidationError, match="validation failed"):
        load_manifest(manifest_file)
