"""Tests for state data models."""

from __future__ import annotations

import pytest

from defined_cli.state.model import (
    MissionRecord,
    RobotState,
    RobotStatus,
    StateSnapshot,
    WorldState,
)


# ---------------------------------------------------------------------------
# RobotStatus
# ---------------------------------------------------------------------------


class TestRobotStatus:

    def test_enum_values_match_strings(self):
        assert RobotStatus.OFFLINE.value == "OFFLINE"
        assert RobotStatus.IDLE.value == "IDLE"
        assert RobotStatus.ON_MISSION.value == "ON_MISSION"
        assert RobotStatus.PAUSED.value == "PAUSED"

    def test_construction_from_string(self):
        assert RobotStatus("IDLE") is RobotStatus.IDLE
        assert RobotStatus("ON_MISSION") is RobotStatus.ON_MISSION

    def test_invalid_string_raises_value_error(self):
        with pytest.raises(ValueError):
            RobotStatus("INVALID")


# ---------------------------------------------------------------------------
# RobotState
# ---------------------------------------------------------------------------


class TestRobotState:

    def test_defaults(self):
        state = RobotState()
        assert state.current is RobotStatus.OFFLINE
        assert state.last_mission_id is None
        assert state.last_mission_result is None

    def test_custom_values(self):
        state = RobotState(
            current=RobotStatus.ON_MISSION,
            last_mission_id="patrol-001",
            last_mission_result="SUCCESS",
        )
        assert state.current is RobotStatus.ON_MISSION
        assert state.last_mission_id == "patrol-001"
        assert state.last_mission_result == "SUCCESS"


# ---------------------------------------------------------------------------
# WorldState
# ---------------------------------------------------------------------------


class TestWorldState:

    def test_defaults_empty_pois(self):
        world = WorldState()
        assert world.pois == {}

    def test_with_poi_entries(self):
        pois = {
            "dock": {"center": {"x": 0.0, "y": 0.0}, "type": "constant"},
            "kitchen": {"center": {"x": 1.5, "y": 2.0}, "type": "static"},
        }
        world = WorldState(pois=pois)
        assert world.pois["dock"]["type"] == "constant"
        assert world.pois["kitchen"]["center"]["x"] == 1.5


# ---------------------------------------------------------------------------
# MissionRecord
# ---------------------------------------------------------------------------


class TestMissionRecord:

    def test_required_fields(self):
        record = MissionRecord(id="m-001", task_name="patrol", status="SUCCESS")
        assert record.id == "m-001"
        assert record.task_name == "patrol"
        assert record.status == "SUCCESS"

    def test_optional_fields_default_to_none(self):
        record = MissionRecord(id="m-001", task_name="patrol", status="PENDING")
        assert record.started_at is None
        assert record.completed_at is None
        assert record.result is None


# ---------------------------------------------------------------------------
# StateSnapshot
# ---------------------------------------------------------------------------


class TestStateSnapshot:

    def test_all_defaults(self):
        snap = StateSnapshot()
        assert snap.robot.current is RobotStatus.OFFLINE
        assert snap.world.pois == {}
        assert snap.mission_queue == []
        assert snap.mission_history == []
        assert snap.schema_version == "1"

    def test_to_dict_serializes_enums_as_strings(self):
        snap = StateSnapshot()
        snap.robot.current = RobotStatus.IDLE
        data = snap.to_dict()
        assert data["robot"]["current"] == "IDLE"
        assert data["schema_version"] == "1"

    def test_to_dict_serializes_mission_history(self):
        record = MissionRecord(
            id="m-001",
            task_name="patrol",
            status="SUCCESS",
            started_at="2026-04-07T10:00:00",
            completed_at="2026-04-07T10:05:00",
            result="All waypoints visited",
        )
        snap = StateSnapshot(mission_history=[record])
        data = snap.to_dict()
        assert data["mission_history"][0]["id"] == "m-001"
        assert data["mission_history"][0]["status"] == "SUCCESS"

    def test_from_dict_roundtrip(self):
        original = StateSnapshot(
            robot=RobotState(current=RobotStatus.IDLE, last_mission_id="p-001"),
            world=WorldState(pois={"dock": {"center": {"x": 0.0, "y": 0.0}}}),
            mission_history=[
                MissionRecord(id="m-001", task_name="patrol", status="SUCCESS"),
            ],
        )
        data = original.to_dict()
        restored = StateSnapshot.from_dict(data)

        assert restored.robot.current is RobotStatus.IDLE
        assert restored.robot.last_mission_id == "p-001"
        assert restored.world.pois["dock"]["center"]["x"] == 0.0
        assert restored.mission_history[0].id == "m-001"
        assert restored.schema_version == "1"

    def test_from_dict_missing_keys_uses_defaults(self):
        snap = StateSnapshot.from_dict({})
        assert snap.robot.current is RobotStatus.OFFLINE
        assert snap.world.pois == {}
        assert snap.mission_queue == []
        assert snap.mission_history == []
        assert snap.schema_version == "1"

    def test_from_dict_partial_robot(self):
        snap = StateSnapshot.from_dict({"robot": {"current": "ON_MISSION"}})
        assert snap.robot.current is RobotStatus.ON_MISSION
        assert snap.robot.last_mission_id is None
