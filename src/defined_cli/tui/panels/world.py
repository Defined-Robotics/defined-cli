"""World panel — POI list."""

from __future__ import annotations

from textual.widgets import Static


class WorldPanel(Static):
    """Displays Points of Interest."""

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._pois: dict[str, dict] = {}

    def update_pois(self, pois: dict[str, dict]) -> None:
        self._pois = pois
        self.refresh()

    def render(self) -> str:
        if not self._pois:
            return "[dim]No POIs defined.\n/world add <name> <x> <y>[/dim]"

        lines = [f"{'Name':<14} {'X':>6} {'Y':>6}  {'Type':<8}", "─" * 38]
        for name, poi in self._pois.items():
            center = poi.get("center", {})
            x = center.get("x", 0.0)
            y = center.get("y", 0.0)
            poi_type = poi.get("type", "static")
            lines.append(f"{name:<14} {x:>6.1f} {y:>6.1f}  {poi_type:<8}")

        return "\n".join(lines)
