"""Spatial blackboard -- dot-path key-value store with POI semantics.

The blackboard is the robot's spatial memory. POIs (Points of Interest)
are first-class entries under ``world.pois.*``, stored with three
type tiers: constant, static, and dynamic.

Usage:
    from defined_cli.state.blackboard import Blackboard

    bb = Blackboard()
    bb.set_poi("dock", (0.0, 0.0), poi_type="constant")
    bb.set_poi("kitchen", (1.5, 2.0))
    print(bb.get_poi("kitchen"))
"""

from __future__ import annotations

import copy
from typing import Any


_POI_PREFIX = "world.pois"


class Blackboard:
    """Nested key-value store with dot-path access and POI convenience methods.

    Wraps a plain dict internally. All access goes through dot-path
    methods to enforce consistent structure.

    Args:
        data: Initial data dict (e.g. loaded from StateStore). Defaults to empty.
    """

    def __init__(self, data: dict | None = None) -> None:
        self._data: dict = copy.deepcopy(data) if data else {}

    # -------------------------------------------------------------------
    # Core dot-path API
    # -------------------------------------------------------------------

    def get(self, key: str, default: Any = None) -> Any:
        """Get a value by dot-path.

        Args:
            key: Dot-separated path (e.g. ``"world.pois.dock"``).
            default: Returned if the path does not exist.

        Returns:
            The value at the path, or *default*.
        """
        parts = key.split(".")
        node = self._data
        for part in parts:
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    def set(self, key: str, value: Any) -> None:
        """Set a value at a dot-path, creating intermediate dicts as needed.

        Args:
            key: Dot-separated path.
            value: Value to store.
        """
        parts = key.split(".")
        node = self._data
        for part in parts[:-1]:
            if part not in node or not isinstance(node[part], dict):
                node[part] = {}
            node = node[part]
        node[parts[-1]] = value

    def delete(self, key: str) -> None:
        """Delete the value at a dot-path.

        Args:
            key: Dot-separated path to delete (e.g. ``"world.pois.dock"``).

        Raises:
            KeyError: If the path does not exist.
        """
        parts = key.split(".")
        node = self._data
        for part in parts[:-1]:
            if not isinstance(node, dict) or part not in node:
                raise KeyError(key)
            node = node[part]
        if not isinstance(node, dict) or parts[-1] not in node:
            raise KeyError(key)
        del node[parts[-1]]

    def list(self, prefix: str) -> dict:
        """Return all children under a dot-path prefix.

        Args:
            prefix: Dot-separated path to a dict node.

        Returns:
            The dict at *prefix*, or an empty dict if the path does not exist.
        """
        result = self.get(prefix)
        if isinstance(result, dict):
            return result
        return {}

    # -------------------------------------------------------------------
    # POI convenience methods
    # -------------------------------------------------------------------

    def set_poi(
        self,
        name: str,
        center: dict | tuple,
        radius: float = 0.5,
        poi_type: str = "static",
        frame: str = "map",
    ) -> None:
        """Add or update a Point of Interest.

        Args:
            name: POI identifier (e.g. ``"kitchen"``).
            center: ``(x, y)`` tuple or ``{"x": ..., "y": ...}`` dict.
            radius: Area radius in meters.
            poi_type: One of ``"constant"``, ``"static"``, ``"dynamic"``.
            frame: Coordinate frame (default ``"map"``).
        """
        if isinstance(center, tuple):
            center = {"x": center[0], "y": center[1]}
        else:
            center = dict(center)

        self.set(f"{_POI_PREFIX}.{name}", {
            "center": center,
            "radius": radius,
            "type": poi_type,
            "frame": frame,
        })

    def get_poi(self, name: str) -> dict | None:
        """Return a POI dict by name, or ``None`` if not found."""
        return self.get(f"{_POI_PREFIX}.{name}")

    def list_pois(self) -> dict[str, dict]:
        """Return all POIs as ``{name: poi_dict}``."""
        return self.list(_POI_PREFIX)

    # -------------------------------------------------------------------
    # Serialization
    # -------------------------------------------------------------------

    def to_dict(self) -> dict:
        """Return a deep copy of the internal data for StateStore serialization."""
        return copy.deepcopy(self._data)

    @classmethod
    def from_dict(cls, data: dict) -> Blackboard:
        """Reconstruct a Blackboard from a plain dict."""
        return cls(data=data)
