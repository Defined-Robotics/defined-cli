"""POI reference resolver -- expands ``$world.pois.X`` in task dicts.

Runs before the compiler. Walks task step params and replaces
string references (``$world.pois.kitchen``) with concrete
coordinate values from the Blackboard.

Usage:
    from defined_cli.mission.resolver import resolve_references

    resolved = resolve_references(task_dict, blackboard)
    # resolved["steps"][0]["params"]["x"] == 1.5
"""

from __future__ import annotations

import copy

from defined_cli.state.blackboard import Blackboard

_REF_PREFIX = "$"


class ResolverError(Exception):
    """A POI reference in the task could not be resolved.

    Attributes:
        reference: The unresolved reference string (e.g. ``"$world.pois.unknown"``).
    """

    def __init__(self, reference: str, message: str) -> None:
        self.reference = reference
        super().__init__(message)


def resolve_references(task_dict: dict, blackboard: Blackboard) -> dict:
    """Resolve all ``$world.pois.X`` references in a task dict.

    Returns a new dict (deep copy) with references replaced by
    concrete values. For ``target`` params pointing to a POI,
    expands the POI center into ``x`` and ``y`` coordinates.

    Args:
        task_dict: Parsed task YAML (from ``parser.load_task``).
        blackboard: Blackboard containing POI data.

    Returns:
        A new task dict with all references resolved.

    Raises:
        ResolverError: If a referenced POI does not exist.
    """
    result = copy.deepcopy(task_dict)

    for step in result.get("steps", []):
        params = step.get("params", {})
        _resolve_params(params, blackboard)
        step["params"] = params

    return result


def _resolve_params(params: dict, blackboard: Blackboard) -> None:
    """Resolve ``$``-prefixed references in a params dict in-place.

    For ``target`` params that resolve to a POI with a ``center``,
    expands the center into ``x`` and ``y`` and removes ``target``.
    """
    keys_to_expand = []

    for key, value in list(params.items()):
        if not isinstance(value, str) or not value.startswith(_REF_PREFIX):
            continue

        path = value[len(_REF_PREFIX):]
        resolved = blackboard.get(path)

        if resolved is None:
            available = list(blackboard.list_pois().keys())
            raise ResolverError(
                reference=value,
                message=(
                    f"POI reference '{value}' could not be resolved. "
                    f"Available POIs: {available}"
                ),
            )

        if (
            key == "target"
            and isinstance(resolved, dict)
            and "center" in resolved
        ):
            keys_to_expand.append((key, resolved))
        else:
            params[key] = resolved

    for key, poi in keys_to_expand:
        center = poi["center"]
        params["x"] = center["x"]
        params["y"] = center["y"]
        del params[key]
