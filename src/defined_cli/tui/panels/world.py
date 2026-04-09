"""World panel — POI list."""

from __future__ import annotations

from typing import TYPE_CHECKING

from defined_cli.tui.panels.base import BasePanel, register_panel

if TYPE_CHECKING:
    from defined_cli.mission.session import DefinedSession


@register_panel
class WorldPanel(BasePanel):
    """Displays Points of Interest."""

    PANEL_TITLE = "WORLD"
    PANEL_ID = "panel-world"

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._pois: dict[str, dict] = {}

    def update_pois(self, pois: dict[str, dict]) -> None:
        """Directly set POI data (useful for testing and non-session use)."""
        self._pois = pois
        self.refresh()

    def on_tick(self, session: DefinedSession) -> None:
        pois = session.list_pois()
        if pois != self._pois:
            self._pois = pois
            self.refresh()

    def render(self) -> str:
        if not self._pois:
            return "[dim]No POIs defined.\n/world add <name> <x> <y>[/dim]"

        lines = [f"{'Name':<12} {'X':>5} {'Y':>5} {'Type'}", "─" * 32]
        for name, poi in self._pois.items():
            center = poi.get("center", {})
            x = center.get("x", 0.0)
            y = center.get("y", 0.0)
            poi_type = poi.get("type", "static")
            lines.append(f"{name:<12} {x:>5.1f} {y:>5.1f} {poi_type}")

        return "\n".join(lines)
