"""Diagnostics panel — timestamped event log with 3-layer progressive disclosure."""

from __future__ import annotations

from collections import deque

from defined_cli.mission.events import SessionEvent
from defined_cli.tui.panels.base import BasePanel, register_panel


@register_panel
class DiagnosticsPanel(BasePanel):
    """Displays diagnostic events with timestamps and 3 detail layers.

    Layer 1 (always): timestamped human-readable messages
    Layer 2 (/detail): suggestions
    Layer 3 (/detail again): structured detail
    """

    PANEL_TITLE = "DIAGNOSTICS"
    PANEL_ID = "panel-diagnostics"

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._events: deque[SessionEvent] = deque(maxlen=50)
        self._detail_level: int = 1  # 1, 2, or 3

    def add_event(self, event: SessionEvent) -> None:
        self._events.append(event)
        self.refresh()

    def on_session_event(self, event: SessionEvent) -> None:
        self.add_event(event)

    def set_detail_level(self, level: int) -> None:
        self._detail_level = max(1, min(3, level))
        self.refresh()

    def cycle_detail(self) -> None:
        self._detail_level = (self._detail_level % 3) + 1
        self.refresh()

    def _format_message(self, event: SessionEvent) -> str:
        """Return a human-readable message for the event."""
        msg = event.message
        cat = event.category

        # Map known patterns to friendlier messages
        if cat == "connection":
            if "connected" in msg.lower() and "dis" not in msg.lower():
                return "Connected to robot via rosbridge"
            if "disconnect" in msg.lower():
                return "Lost connection to robot"
            if "reconnect" in msg.lower():
                return "Reconnecting..."
        if cat == "error":
            return f"Error: {msg}"

        return msg

    def render(self) -> str:
        if not self._events:
            return "[dim]Waiting for events...[/dim]"

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

            # Timestamp
            ts = event.timestamp.strftime("%H:%M:%S")
            human_msg = self._format_message(event)

            # Layer 1: always show timestamped message
            lines.append(f"[dim]{ts}[/dim]  [{color}]{human_msg}[/{color}]")

            # Layer 2: show suggestion if detail_level >= 2
            if self._detail_level >= 2 and event.suggestion:
                lines.append(f"         [yellow]→ {event.suggestion}[/yellow]")

            # Layer 3: show raw detail if detail_level >= 3
            if self._detail_level >= 3 and event.detail:
                for k, v in event.detail.items():
                    lines.append(f"         [dim]{k}: {v}[/dim]")

        level_label = {1: "Summary", 2: "Suggestions", 3: "Advanced"}.get(self._detail_level, "")
        lines.append(f"\n[dim]Detail: {level_label} (/detail to cycle)[/dim]")
        return "\n".join(lines)
