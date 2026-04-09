"""Diagnostics panel — 3-layer progressive disclosure."""

from __future__ import annotations

from collections import deque

from textual.widgets import Static

from defined_cli.mission.events import SessionEvent


class DiagnosticsPanel(Static):
    """Displays diagnostic events with 3 detail layers.

    Layer 1 (always): event messages
    Layer 2 (press d): suggestions
    Layer 3 (press D): structured detail
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._events: deque[SessionEvent] = deque(maxlen=50)
        self._detail_level: int = 1  # 1, 2, or 3

    def add_event(self, event: SessionEvent) -> None:
        self._events.append(event)
        self.refresh()

    def set_detail_level(self, level: int) -> None:
        self._detail_level = max(1, min(3, level))
        self.refresh()

    def cycle_detail(self) -> None:
        self._detail_level = (self._detail_level % 3) + 1
        self.refresh()

    def render(self) -> str:
        if not self._events:
            return "[dim]No diagnostics yet.[/dim]"

        lines = []
        recent = list(self._events)[-12:]
        for event in recent:
            # Category color
            color = {
                "connection": "blue",
                "executor": "cyan",
                "mission": "green",
                "error": "red",
            }.get(event.category, "white")

            # Layer 1: always show message
            lines.append(f"[{color}]{event.message}[/{color}]")

            # Layer 2: show suggestion if detail_level >= 2
            if self._detail_level >= 2 and event.suggestion:
                lines.append(f"  [yellow]→ {event.suggestion}[/yellow]")

            # Layer 3: show raw detail if detail_level >= 3
            if self._detail_level >= 3 and event.detail:
                for k, v in event.detail.items():
                    lines.append(f"  [dim]{k}: {v}[/dim]")

        level_label = {1: "Summary", 2: "Suggestions", 3: "Advanced"}.get(self._detail_level, "")
        lines.append(f"\n[dim]Detail: {level_label} (d/D to change)[/dim]")
        return "\n".join(lines)
