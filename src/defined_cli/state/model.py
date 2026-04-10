"""State data models -- robot status, world state, and mission records.

Pure data containers with no I/O, no CLI dependencies, and no side effects.
Used by ``StateStore`` for persistence and ``Blackboard`` for spatial memory.

Usage:
    from defined_cli.state.model import StateSnapshot, RobotStatus

    snapshot = StateSnapshot()
    snapshot.robot.current = RobotStatus.IDLE
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum


class RobotStatus(Enum):
    """Robot lifecycle states.

    Transitions:
        OFFLINE -> IDLE -> ON_MISSION -> IDLE
                          ON_MISSION -> PAUSED -> ON_MISSION | IDLE
    """

    OFFLINE = "OFFLINE"
    IDLE = "IDLE"
    ON_MISSION = "ON_MISSION"
    PAUSED = "PAUSED"


@dataclass
class RobotState:
    """Current robot status and last mission metadata.

    Attributes:
        current: Active lifecycle state.
        last_mission_id: ID of the most recently completed mission.
        last_mission_result: Outcome of the last mission (SUCCESS, FAILURE, ABORTED).
    """

    current: RobotStatus = RobotStatus.OFFLINE
    last_mission_id: str | None = None
    last_mission_result: str | None = None


@dataclass
class WorldState:
    """Spatial world model -- POIs keyed by name.

    Each POI value is a plain dict:
    ``{"center": {"x": ..., "y": ...}, "radius": ..., "type": ..., "frame": ...}``

    Attributes:
        pois: Map of POI name to spatial entity dict.
    """

    pois: dict[str, dict] = field(default_factory=dict)


@dataclass
class MissionRecord:
    """Completed or in-progress mission metadata.

    Attributes:
        id: Unique mission identifier.
        task_name: Name from the task YAML.
        status: One of PENDING, RUNNING, SUCCESS, FAILURE, ABORTED.
        started_at: ISO 8601 timestamp, or None if not yet started.
        completed_at: ISO 8601 timestamp, or None if not yet finished.
        result: Human-readable result summary.
    """

    id: str
    task_name: str
    status: str
    started_at: str | None = None
    completed_at: str | None = None
    result: str | None = None


@dataclass
class StateSnapshot:
    """Full robot state -- persisted to ``~/.defined/state.yaml``.

    Attributes:
        robot: Current robot lifecycle state.
        world: Spatial world model (POIs).
        mission_queue: FIFO queue of pending mission dicts.
        mission_history: Completed mission records.
        schema_version: State file format version for future migrations.
    """

    robot: RobotState = field(default_factory=RobotState)
    world: WorldState = field(default_factory=WorldState)
    mission_queue: list[dict] = field(default_factory=list)
    mission_history: list[MissionRecord] = field(default_factory=list)
    schema_version: str = "1"

    def to_dict(self) -> dict:
        """Serialize to a plain dict suitable for ``yaml.dump``.

        Converts enums to their string values and dataclasses to
        plain dicts for YAML serialization.

        Returns:
            A plain dict with no dataclass or enum instances.
        """
        return {
            "schema_version": self.schema_version,
            "robot": {
                "current": self.robot.current.value,
                "last_mission_id": self.robot.last_mission_id,
                "last_mission_result": self.robot.last_mission_result,
            },
            "world": {"pois": self.world.pois},
            "mission_queue": self.mission_queue,
            "mission_history": [asdict(r) for r in self.mission_history],
        }

    @classmethod
    def from_dict(cls, data: dict) -> StateSnapshot:
        """Reconstruct from a YAML-loaded dict. Missing keys use defaults.

        Args:
            data: Plain dict, typically from ``yaml.safe_load``.

        Returns:
            A populated ``StateSnapshot``.
        """
        robot_data = data.get("robot", {})
        robot = RobotState(
            current=RobotStatus(robot_data.get("current", "OFFLINE")),
            last_mission_id=robot_data.get("last_mission_id"),
            last_mission_result=robot_data.get("last_mission_result"),
        )

        world_data = data.get("world", {})
        world = WorldState(pois=world_data.get("pois", {}))

        history = [
            MissionRecord(**record)
            for record in data.get("mission_history", [])
        ]

        return cls(
            robot=robot,
            world=world,
            mission_queue=data.get("mission_queue", []),
            mission_history=history,
            schema_version=data.get("schema_version", "1"),
        )
