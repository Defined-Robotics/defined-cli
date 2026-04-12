"""Tests for the session launcher module.

Covers:
- try_load_manifest: returns None on missing/invalid, returns manifest on valid
- try_load_world: returns None when no manifest/world, loads valid world
- seed_world_pois: seeds POIs into state store
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from defined_cli.launcher import (
    try_load_manifest,
    try_load_world,
    seed_world_pois,
)
from defined_cli.manifest import ProjectManifest
from defined_cli.state.store import StateStore
from defined_cli.state.world_loader import WorldDefinition


# ---------------------------------------------------------------------------
# try_load_manifest
# ---------------------------------------------------------------------------


class TestTryLoadManifest:

    def test_returns_none_when_path_is_none(self) -> None:
        """Preconditions: No manifest path provided.
        Tests: try_load_manifest returns None gracefully.
        Success: Return value is None, no exception.
        """
        assert try_load_manifest(None) is None

    def test_returns_none_for_missing_file(self, tmp_path: Path) -> None:
        """Preconditions: Path points to nonexistent file.
        Tests: try_load_manifest returns None instead of raising.
        Success: Return value is None.
        """
        assert try_load_manifest(tmp_path / "nope.yaml") is None

    def test_returns_none_for_invalid_yaml(self, tmp_path: Path) -> None:
        """Preconditions: File exists but contains invalid YAML.
        Tests: try_load_manifest catches validation error, returns None.
        Success: Return value is None.
        """
        bad = tmp_path / "defined.yaml"
        bad.write_text("not:\n  valid yaml\n bad indent\n")
        assert try_load_manifest(bad) is None

    def test_returns_none_for_incomplete_manifest(self, tmp_path: Path) -> None:
        """Preconditions: File is valid YAML but missing required fields.
        Tests: try_load_manifest catches Pydantic validation error, returns None.
        Success: Return value is None.
        """
        incomplete = tmp_path / "defined.yaml"
        incomplete.write_text("project:\n  name: test\n")  # missing robot section
        assert try_load_manifest(incomplete) is None

    def test_returns_manifest_for_valid_file(self, tmp_path: Path) -> None:
        """Preconditions: File is a valid minimal manifest.
        Tests: try_load_manifest returns a ProjectManifest instance.
        Success: Returned manifest has correct project name.
        """
        valid = tmp_path / "defined.yaml"
        valid.write_text("project:\n  name: test\nrobot:\n  rdf: r.yaml\n")
        result = try_load_manifest(valid)
        assert result is not None
        assert result.project.name == "test"


# ---------------------------------------------------------------------------
# try_load_world
# ---------------------------------------------------------------------------


class TestTryLoadWorld:

    def test_returns_none_when_no_manifest(self) -> None:
        """Preconditions: No manifest provided.
        Tests: try_load_world returns None without error.
        Success: Return value is None.
        """
        assert try_load_world(None) is None

    def test_returns_none_when_no_world_section(self) -> None:
        """Preconditions: Manifest exists but has no world section.
        Tests: try_load_world returns None.
        Success: Return value is None.
        """
        manifest = ProjectManifest.model_validate({
            "project": {"name": "test"},
            "robot": {"rdf": "r.yaml"},
        })
        assert try_load_world(manifest) is None

    def test_returns_none_when_world_file_missing(self, tmp_path: Path) -> None:
        """Preconditions: Manifest references a world file that doesn't exist.
        Tests: try_load_world returns None instead of raising.
        Success: Return value is None.
        """
        manifest = ProjectManifest.model_validate({
            "project": {"name": "test"},
            "robot": {"rdf": "r.yaml"},
            "world": {"file": str(tmp_path / "nope.yaml")},
        })
        assert try_load_world(manifest) is None

    def test_loads_valid_world(self, tmp_path: Path) -> None:
        """Preconditions: Manifest references an existing, valid world file.
        Tests: try_load_world returns a WorldDefinition.
        Success: Returned world has correct name and POI count.
        """
        world_file = tmp_path / "world.yaml"
        world_file.write_text("name: maze\npois:\n  dock:\n    x: 0\n    y: 0\n")
        manifest = ProjectManifest.model_validate({
            "project": {"name": "test"},
            "robot": {"rdf": "r.yaml"},
            "world": {"file": str(world_file)},
        })
        result = try_load_world(manifest)
        assert result is not None
        assert result.name == "maze"
        assert len(result.pois) == 1


# ---------------------------------------------------------------------------
# seed_world_pois
# ---------------------------------------------------------------------------


class TestSeedWorldPois:

    def test_seeds_pois_into_store(self, tmp_path: Path) -> None:
        """Preconditions: World has 2 POIs; state store is fresh.
        Tests: seed_world_pois writes POIs to the state store.
        Success: Reloaded snapshot contains both POIs with correct coords.
        """
        world = WorldDefinition.model_validate({
            "name": "test",
            "pois": {
                "dock": {"x": 0.0, "y": 0.0, "type": "constant"},
                "kitchen": {"x": 1.5, "y": 2.0},
            },
        })
        store = StateStore(path=tmp_path / "state.yaml")
        seed_world_pois(world, store)

        snapshot = store.load()
        assert "dock" in snapshot.world.pois
        assert "kitchen" in snapshot.world.pois
        assert snapshot.world.pois["dock"]["center"]["x"] == 0.0
