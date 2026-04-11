"""World definition loader and blackboard seeding.

Loads ``world.yaml`` and populates the spatial blackboard with POIs.
This module has zero CLI-specific imports (no click, rich, textual).

Usage:
    from defined_cli.state.world_loader import load_world, seed_blackboard
    from defined_cli.state.blackboard import Blackboard

    world = load_world(Path("world.yaml"))
    bb = Blackboard()
    seed_blackboard(world, bb)
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel

from defined_cli.state.blackboard import Blackboard


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class POIDefinition(BaseModel):
    """A Point of Interest in the world definition."""

    x: float
    y: float
    type: str = "static"
    description: str = ""


class SpawnPosition(BaseModel):
    """Robot spawn position for simulation."""

    x: float = 0.0
    y: float = 0.0
    yaw: float = 0.0


class SimEnvironment(BaseModel):
    """Simulation environment configuration."""

    environment: str
    spawn: SpawnPosition = SpawnPosition()


class ZoneDefinition(BaseModel, extra="allow"):
    """A zone boundary (parsed but not enforced in v0.1.0)."""

    x_min: float = 0.0
    x_max: float = 0.0
    y_min: float = 0.0
    y_max: float = 0.0


class WorldDefinition(BaseModel):
    """Complete world definition from world.yaml."""

    name: str
    description: str = ""
    pois: dict[str, POIDefinition] = {}
    zones: dict[str, list[ZoneDefinition]] = {}
    sim: SimEnvironment | None = None


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def load_world(path: Path) -> WorldDefinition:
    """Parse and validate a world.yaml file.

    Args:
        path: Path to the world.yaml file.

    Returns:
        Validated WorldDefinition.
    """
    raw = yaml.safe_load(path.read_text())
    return WorldDefinition.model_validate(raw)


# ---------------------------------------------------------------------------
# Blackboard seeding
# ---------------------------------------------------------------------------


def seed_blackboard(world: WorldDefinition, blackboard: Blackboard) -> None:
    """Populate blackboard with POIs from a world definition.

    POIs are added via ``Blackboard.set_poi()``, which handles the
    conversion to the internal format (center, radius, type, frame).
    Existing POIs in the blackboard are preserved (merge, not replace).

    Args:
        world: Parsed world definition.
        blackboard: Blackboard to populate.
    """
    for name, poi in world.pois.items():
        blackboard.set_poi(
            name,
            center=(poi.x, poi.y),
            poi_type=poi.type,
        )
