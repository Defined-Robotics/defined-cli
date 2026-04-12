"""Tests for the spatial Blackboard -- dot-path access and POI methods."""

from __future__ import annotations

import pytest

from defined_cli.state.blackboard import Blackboard


# ---------------------------------------------------------------------------
# Core dot-path API
# ---------------------------------------------------------------------------


class TestDotPathAccess:

    def test_set_and_get_simple_key(self):
        bb = Blackboard()
        bb.set("color", "red")
        assert bb.get("color") == "red"

    def test_set_and_get_nested_key(self):
        bb = Blackboard()
        bb.set("a.b.c", 42)
        assert bb.get("a.b.c") == 42

    def test_get_nonexistent_returns_default(self):
        bb = Blackboard()
        assert bb.get("x.y.z") is None

    def test_get_with_custom_default(self):
        bb = Blackboard()
        assert bb.get("missing", default="nope") == "nope"

    def test_set_creates_intermediate_dicts(self):
        bb = Blackboard()
        bb.set("a.b.c", 1)
        intermediate = bb.get("a.b")
        assert isinstance(intermediate, dict)
        assert intermediate["c"] == 1

    def test_set_overwrites_existing_value(self):
        bb = Blackboard()
        bb.set("key", "old")
        bb.set("key", "new")
        assert bb.get("key") == "new"

    def test_delete_existing_key(self):
        bb = Blackboard()
        bb.set("a.b", 10)
        bb.delete("a.b")
        assert bb.get("a.b") is None

    def test_delete_nonexistent_raises_key_error(self):
        bb = Blackboard()
        with pytest.raises(KeyError):
            bb.delete("nonexistent")

    def test_list_returns_children_at_prefix(self):
        bb = Blackboard()
        bb.set("world.pois.dock", {"x": 0})
        bb.set("world.pois.kitchen", {"x": 1})
        children = bb.list("world.pois")
        assert "dock" in children
        assert "kitchen" in children
        assert len(children) == 2

    def test_list_empty_prefix_returns_empty_dict(self):
        bb = Blackboard()
        assert bb.list("nonexistent.path") == {}


# ---------------------------------------------------------------------------
# POI convenience methods
# ---------------------------------------------------------------------------


class TestPOIMethods:

    def test_set_poi_with_tuple_center(self):
        bb = Blackboard()
        bb.set_poi("dock", (0.0, 0.0))
        poi = bb.get_poi("dock")
        assert poi is not None
        assert poi["center"] == {"x": 0.0, "y": 0.0}

    def test_set_poi_with_dict_center(self):
        bb = Blackboard()
        bb.set_poi("dock", {"x": 0.0, "y": 0.0})
        poi = bb.get_poi("dock")
        assert poi["center"] == {"x": 0.0, "y": 0.0}

    def test_set_poi_default_values(self):
        bb = Blackboard()
        bb.set_poi("survey", (1.0, 2.0))
        poi = bb.get_poi("survey")
        assert poi["radius"] == 0.5
        assert poi["type"] == "static"
        assert poi["frame"] == "map"

    def test_set_poi_custom_type_constant(self):
        bb = Blackboard()
        bb.set_poi("dock", (0.0, 0.0), poi_type="constant", radius=0.3)
        poi = bb.get_poi("dock")
        assert poi["type"] == "constant"
        assert poi["radius"] == 0.3

    def test_get_poi_exists(self):
        bb = Blackboard()
        bb.set_poi("kitchen", (1.5, 2.0))
        poi = bb.get_poi("kitchen")
        assert poi is not None
        assert poi["center"]["x"] == 1.5

    def test_get_poi_not_found_returns_none(self):
        bb = Blackboard()
        assert bb.get_poi("nonexistent") is None

    def test_list_pois_empty(self):
        bb = Blackboard()
        assert bb.list_pois() == {}

    def test_list_pois_multiple(self):
        bb = Blackboard()
        bb.set_poi("dock", (0.0, 0.0), poi_type="constant")
        bb.set_poi("kitchen", (1.5, 2.0))
        bb.set_poi("survey-1", (3.0, 1.0))
        pois = bb.list_pois()
        assert len(pois) == 3
        assert "dock" in pois
        assert "kitchen" in pois
        assert "survey-1" in pois


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------


class TestSerialization:

    def test_to_dict_returns_deep_copy(self):
        bb = Blackboard()
        bb.set_poi("dock", (0.0, 0.0))
        data = bb.to_dict()
        assert "world" in data
        assert "pois" in data["world"]

    def test_from_dict_reconstructs(self):
        data = {"world": {"pois": {"dock": {"center": {"x": 0.0, "y": 0.0}}}}}
        bb = Blackboard.from_dict(data)
        assert bb.get_poi("dock")["center"]["x"] == 0.0

    def test_to_dict_from_dict_roundtrip(self):
        bb = Blackboard()
        bb.set_poi("dock", (0.0, 0.0), poi_type="constant")
        bb.set_poi("kitchen", (1.5, 2.0))
        bb.set("robot.name", "turtlebot")

        data = bb.to_dict()
        restored = Blackboard.from_dict(data)

        assert restored.get_poi("dock")["type"] == "constant"
        assert restored.get_poi("kitchen")["center"]["y"] == 2.0
        assert restored.get("robot.name") == "turtlebot"

    def test_mutation_of_to_dict_does_not_affect_blackboard(self):
        bb = Blackboard()
        bb.set_poi("dock", (0.0, 0.0))
        data = bb.to_dict()
        data["world"]["pois"]["dock"]["center"]["x"] = 999.0
        assert bb.get_poi("dock")["center"]["x"] == 0.0


# ---------------------------------------------------------------------------
# Clear methods
# ---------------------------------------------------------------------------


class TestClear:

    def test_clear_removes_all_data(self):
        """Preconditions: Blackboard has POIs and other data.
        Tests: clear() removes everything.
        Success: to_dict() returns empty dict, no POIs remain.
        """
        bb = Blackboard()
        bb.set_poi("dock", (0.0, 0.0))
        bb.set("robot.name", "turtlebot")
        bb.clear()

        assert bb.to_dict() == {}
        assert bb.list_pois() == {}
        assert bb.get("robot.name") is None

    def test_clear_pois_removes_only_pois(self):
        """Preconditions: Blackboard has POIs and other data under world.
        Tests: clear_pois() removes POIs but preserves other data.
        Success: list_pois() empty, other data intact.
        """
        bb = Blackboard()
        bb.set_poi("dock", (0.0, 0.0))
        bb.set("robot.name", "turtlebot")
        bb.clear_pois()

        assert bb.list_pois() == {}
        assert bb.get("robot.name") == "turtlebot"

    def test_clear_pois_noop_when_empty(self):
        """Preconditions: Blackboard has no POIs.
        Tests: clear_pois() is safe to call on empty blackboard.
        Success: No exception raised.
        """
        bb = Blackboard()
        bb.clear_pois()
        assert bb.list_pois() == {}
