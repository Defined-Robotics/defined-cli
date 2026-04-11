"""Tests for world.yaml loading and blackboard seeding.

Covers:
- WorldDefinition parsing (POIs, zones, sim section)
- Blackboard seeding from world definition
- Merge semantics (world POIs add to, not replace, existing POIs)
"""

from pathlib import Path

import pytest

from defined_cli.state.blackboard import Blackboard
from defined_cli.state.world_loader import (
    WorldDefinition,
    load_world,
    seed_blackboard,
)


# ---------------------------------------------------------------------------
# World loading
# ---------------------------------------------------------------------------


def test_load_world_with_pois(tmp_path: Path) -> None:
    """Load a world.yaml with POIs."""
    world_file = tmp_path / "world.yaml"
    world_file.write_text(
        "name: test-world\n"
        "pois:\n"
        "  dock:\n"
        "    x: 0.0\n"
        "    y: 0.0\n"
        "    type: constant\n"
        "  kitchen:\n"
        "    x: 1.5\n"
        "    y: 2.0\n"
        "    description: Main kitchen area\n"
    )
    world = load_world(world_file)

    assert world.name == "test-world"
    assert len(world.pois) == 2
    assert world.pois["dock"].x == 0.0
    assert world.pois["dock"].type == "constant"
    assert world.pois["kitchen"].x == 1.5
    assert world.pois["kitchen"].description == "Main kitchen area"


def test_load_world_with_sim_section(tmp_path: Path) -> None:
    """Load a world.yaml with simulation configuration."""
    world_file = tmp_path / "world.yaml"
    world_file.write_text(
        "name: maze\n"
        "sim:\n"
        "  environment: maze_10x10\n"
        "  spawn:\n"
        "    x: 0.5\n"
        "    y: 0.5\n"
        "    yaw: 0.0\n"
    )
    world = load_world(world_file)

    assert world.sim is not None
    assert world.sim.environment == "maze_10x10"
    assert world.sim.spawn.x == 0.5
    assert world.sim.spawn.yaw == 0.0


def test_load_world_with_zones(tmp_path: Path) -> None:
    """Load a world.yaml with zones (parsed but not enforced in v0.1.0)."""
    world_file = tmp_path / "world.yaml"
    world_file.write_text(
        "name: warehouse\n"
        "zones:\n"
        "  no_go:\n"
        "    - x_min: 0.0\n"
        "      x_max: 1.0\n"
        "      y_min: 0.0\n"
        "      y_max: 1.0\n"
    )
    world = load_world(world_file)

    assert len(world.zones) == 1
    assert "no_go" in world.zones
    assert len(world.zones["no_go"]) == 1


def test_load_world_minimal(tmp_path: Path) -> None:
    """A world with only a name is valid."""
    world_file = tmp_path / "world.yaml"
    world_file.write_text("name: empty\n")
    world = load_world(world_file)

    assert world.name == "empty"
    assert world.pois == {}
    assert world.zones == {}
    assert world.sim is None


def test_poi_type_defaults_to_static(tmp_path: Path) -> None:
    """POI type defaults to 'static' when not specified."""
    world_file = tmp_path / "world.yaml"
    world_file.write_text(
        "name: test\n"
        "pois:\n"
        "  waypoint:\n"
        "    x: 1.0\n"
        "    y: 2.0\n"
    )
    world = load_world(world_file)
    assert world.pois["waypoint"].type == "static"


# ---------------------------------------------------------------------------
# Blackboard seeding
# ---------------------------------------------------------------------------


def test_seed_blackboard_from_world() -> None:
    """POIs from world definition end up in blackboard with correct format."""
    world = WorldDefinition.model_validate({
        "name": "test",
        "pois": {
            "dock": {"x": 0.0, "y": 0.0, "type": "constant"},
            "kitchen": {"x": 1.5, "y": 2.0},
        },
    })
    bb = Blackboard()
    seed_blackboard(world, bb)

    dock = bb.get_poi("dock")
    assert dock is not None
    assert dock["center"]["x"] == 0.0
    assert dock["center"]["y"] == 0.0
    assert dock["type"] == "constant"

    kitchen = bb.get_poi("kitchen")
    assert kitchen is not None
    assert kitchen["center"]["x"] == 1.5
    assert kitchen["center"]["y"] == 2.0
    assert kitchen["type"] == "static"


def test_seed_blackboard_preserves_existing_pois() -> None:
    """World POIs merge with, not replace, existing blackboard POIs."""
    bb = Blackboard()
    bb.set_poi("existing", (5.0, 5.0), poi_type="dynamic")

    world = WorldDefinition.model_validate({
        "name": "test",
        "pois": {
            "dock": {"x": 0.0, "y": 0.0},
        },
    })
    seed_blackboard(world, bb)

    # Both POIs should exist
    assert bb.get_poi("existing") is not None
    assert bb.get_poi("existing")["center"]["x"] == 5.0
    assert bb.get_poi("dock") is not None


def test_seed_blackboard_empty_world() -> None:
    """Seeding with a world that has no POIs is a no-op."""
    bb = Blackboard()
    bb.set_poi("existing", (1.0, 1.0))

    world = WorldDefinition.model_validate({"name": "empty"})
    seed_blackboard(world, bb)

    assert bb.get_poi("existing") is not None
    assert bb.list_pois() == {"existing": bb.get_poi("existing")}
