"""Tests for StateStore -- atomic YAML persistence."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from defined_cli.state.model import (
    MissionRecord,
    RobotState,
    RobotStatus,
    StateSnapshot,
    WorldState,
)
from defined_cli.state.store import StateStore


class TestStateStore:

    def test_load_returns_default_when_no_file(self, tmp_path: Path):
        store = StateStore(path=tmp_path / "state.yaml")
        snap = store.load()
        assert snap.robot.current is RobotStatus.OFFLINE
        assert snap.world.pois == {}
        assert snap.schema_version == "1"

    def test_save_creates_parent_directory(self, tmp_path: Path):
        nested = tmp_path / "deep" / "nested" / "state.yaml"
        store = StateStore(path=nested)
        store.save(StateSnapshot())
        assert nested.exists()

    def test_save_and_load_roundtrip(self, tmp_path: Path):
        store = StateStore(path=tmp_path / "state.yaml")
        original = StateSnapshot(
            robot=RobotState(current=RobotStatus.IDLE, last_mission_id="p-001"),
            world=WorldState(pois={"dock": {"center": {"x": 0.0, "y": 0.0}}}),
        )
        store.save(original)
        restored = store.load()

        assert restored.robot.current is RobotStatus.IDLE
        assert restored.robot.last_mission_id == "p-001"
        assert restored.world.pois["dock"]["center"]["x"] == 0.0

    def test_save_writes_valid_yaml(self, tmp_path: Path):
        path = tmp_path / "state.yaml"
        store = StateStore(path=path)
        store.save(StateSnapshot(robot=RobotState(current=RobotStatus.IDLE)))

        raw = yaml.safe_load(path.read_text())
        assert raw["robot"]["current"] == "IDLE"
        assert raw["schema_version"] == "1"

    def test_load_existing_file(self, tmp_path: Path):
        path = tmp_path / "state.yaml"
        path.write_text(
            yaml.dump({
                "schema_version": "1",
                "robot": {"current": "ON_MISSION", "last_mission_id": "m-42"},
                "world": {"pois": {"survey-1": {"center": {"x": 1.0, "y": 2.0}}}},
                "mission_queue": [],
                "mission_history": [],
            })
        )
        store = StateStore(path=path)
        snap = store.load()

        assert snap.robot.current is RobotStatus.ON_MISSION
        assert snap.robot.last_mission_id == "m-42"
        assert snap.world.pois["survey-1"]["center"]["y"] == 2.0

    def test_load_corrupted_yaml_raises(self, tmp_path: Path):
        path = tmp_path / "state.yaml"
        path.write_text(":::\n  bad:\n    -yaml\n  [[[")
        store = StateStore(path=path)
        with pytest.raises(yaml.YAMLError):
            store.load()

    def test_custom_path(self, tmp_path: Path):
        custom = tmp_path / "custom" / "robot.yaml"
        store = StateStore(path=custom)
        assert store.path == custom

    def test_schema_version_preserved(self, tmp_path: Path):
        store = StateStore(path=tmp_path / "state.yaml")
        snap = StateSnapshot(schema_version="2")
        store.save(snap)
        restored = store.load()
        assert restored.schema_version == "2"

    def test_full_snapshot_with_pois_and_history(self, tmp_path: Path):
        store = StateStore(path=tmp_path / "state.yaml")
        snap = StateSnapshot(
            robot=RobotState(
                current=RobotStatus.IDLE,
                last_mission_id="patrol-003",
                last_mission_result="SUCCESS",
            ),
            world=WorldState(
                pois={
                    "dock": {
                        "center": {"x": 0.0, "y": 0.0},
                        "radius": 0.3,
                        "type": "constant",
                        "frame": "map",
                    },
                    "kitchen": {
                        "center": {"x": 1.5, "y": 2.0},
                        "radius": 0.5,
                        "type": "static",
                        "frame": "map",
                    },
                }
            ),
            mission_history=[
                MissionRecord(
                    id="patrol-003",
                    task_name="patrol",
                    status="SUCCESS",
                    started_at="2026-04-07T10:00:00",
                    completed_at="2026-04-07T10:05:00",
                ),
            ],
        )
        store.save(snap)
        restored = store.load()

        assert len(restored.world.pois) == 2
        assert restored.world.pois["dock"]["type"] == "constant"
        assert restored.mission_history[0].task_name == "patrol"
        assert restored.robot.last_mission_result == "SUCCESS"

    def test_save_overwrites_existing_file(self, tmp_path: Path):
        path = tmp_path / "state.yaml"
        store = StateStore(path=path)

        store.save(StateSnapshot(robot=RobotState(current=RobotStatus.IDLE)))
        store.save(StateSnapshot(robot=RobotState(current=RobotStatus.ON_MISSION)))

        restored = store.load()
        assert restored.robot.current is RobotStatus.ON_MISSION
