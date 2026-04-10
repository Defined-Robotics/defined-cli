"""Tests for the POI reference resolver."""

from __future__ import annotations

import pytest

from defined_cli.mission.resolver import ResolverError, resolve_references
from defined_cli.state.blackboard import Blackboard


def _make_blackboard() -> Blackboard:
    """Create a Blackboard pre-loaded with test POIs."""
    bb = Blackboard()
    bb.set_poi("kitchen", (1.5, 2.0))
    bb.set_poi("dock", (0.0, 0.0), poi_type="constant")
    bb.set_poi("survey-1", (3.0, 1.0))
    return bb


# ---------------------------------------------------------------------------
# Reference resolution
# ---------------------------------------------------------------------------


class TestResolveReferences:

    def test_no_references_passes_through_unchanged(self):
        bb = _make_blackboard()
        task = {
            "name": "patrol",
            "steps": [{"verb": "go_to", "params": {"x": 1.0, "y": 2.0}}],
        }
        resolved = resolve_references(task, bb)
        assert resolved["steps"][0]["params"] == {"x": 1.0, "y": 2.0}

    def test_resolve_single_target_to_coordinates(self):
        bb = _make_blackboard()
        task = {
            "name": "visit",
            "steps": [{"verb": "go_to", "params": {"target": "$world.pois.kitchen"}}],
        }
        resolved = resolve_references(task, bb)
        params = resolved["steps"][0]["params"]
        assert params["x"] == 1.5
        assert params["y"] == 2.0
        assert "target" not in params

    def test_resolve_multiple_steps_with_different_pois(self):
        bb = _make_blackboard()
        task = {
            "name": "patrol",
            "steps": [
                {"verb": "go_to", "params": {"target": "$world.pois.kitchen"}},
                {"verb": "report", "params": {"message": "arrived"}},
                {"verb": "go_to", "params": {"target": "$world.pois.dock"}},
            ],
        }
        resolved = resolve_references(task, bb)
        assert resolved["steps"][0]["params"]["x"] == 1.5
        assert resolved["steps"][1]["params"]["message"] == "arrived"
        assert resolved["steps"][2]["params"]["x"] == 0.0

    def test_unknown_poi_raises_resolver_error(self):
        bb = _make_blackboard()
        task = {
            "name": "visit",
            "steps": [{"verb": "go_to", "params": {"target": "$world.pois.nonexistent"}}],
        }
        with pytest.raises(ResolverError) as exc_info:
            resolve_references(task, bb)
        assert "nonexistent" in str(exc_info.value)

    def test_error_message_lists_available_pois(self):
        bb = _make_blackboard()
        task = {
            "name": "visit",
            "steps": [{"verb": "go_to", "params": {"target": "$world.pois.unknown"}}],
        }
        with pytest.raises(ResolverError, match="kitchen"):
            resolve_references(task, bb)

    def test_does_not_mutate_input_dict(self):
        bb = _make_blackboard()
        task = {
            "name": "visit",
            "steps": [{"verb": "go_to", "params": {"target": "$world.pois.kitchen"}}],
        }
        resolve_references(task, bb)
        assert task["steps"][0]["params"]["target"] == "$world.pois.kitchen"

    def test_non_target_reference_resolves_to_full_poi_dict(self):
        bb = _make_blackboard()
        task = {
            "name": "inspect",
            "steps": [{"verb": "inspect", "params": {"location": "$world.pois.kitchen"}}],
        }
        resolved = resolve_references(task, bb)
        location = resolved["steps"][0]["params"]["location"]
        assert isinstance(location, dict)
        assert location["center"]["x"] == 1.5

    def test_mixed_references_and_literal_values(self):
        bb = _make_blackboard()
        task = {
            "name": "visit",
            "steps": [{
                "verb": "go_to",
                "params": {"target": "$world.pois.kitchen", "speed": 0.5},
            }],
        }
        resolved = resolve_references(task, bb)
        params = resolved["steps"][0]["params"]
        assert params["x"] == 1.5
        assert params["speed"] == 0.5

    def test_numeric_params_untouched(self):
        bb = _make_blackboard()
        task = {
            "name": "wait",
            "steps": [{"verb": "wait", "params": {"duration": 5.0}}],
        }
        resolved = resolve_references(task, bb)
        assert resolved["steps"][0]["params"]["duration"] == 5.0


# ---------------------------------------------------------------------------
# Target expansion
# ---------------------------------------------------------------------------


class TestTargetExpansion:

    def test_target_key_expands_to_x_y_from_center(self):
        bb = _make_blackboard()
        task = {
            "name": "go",
            "steps": [{"verb": "go_to", "params": {"target": "$world.pois.survey-1"}}],
        }
        resolved = resolve_references(task, bb)
        params = resolved["steps"][0]["params"]
        assert params["x"] == 3.0
        assert params["y"] == 1.0
        assert "target" not in params

    def test_target_expansion_preserves_other_params(self):
        bb = _make_blackboard()
        task = {
            "name": "go",
            "steps": [{
                "verb": "go_to",
                "params": {
                    "target": "$world.pois.kitchen",
                    "theta": 1.57,
                    "timeout": 30.0,
                },
            }],
        }
        resolved = resolve_references(task, bb)
        params = resolved["steps"][0]["params"]
        assert params["x"] == 1.5
        assert params["y"] == 2.0
        assert params["theta"] == 1.57
        assert params["timeout"] == 30.0

    def test_target_with_non_poi_value_kept_as_is(self):
        bb = Blackboard()
        bb.set("world.pois.simple", "just-a-string")
        task = {
            "name": "go",
            "steps": [{"verb": "go_to", "params": {"target": "$world.pois.simple"}}],
        }
        resolved = resolve_references(task, bb)
        assert resolved["steps"][0]["params"]["target"] == "just-a-string"
