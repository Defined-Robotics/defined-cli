"""Status bar widget — connection, task, elapsed time."""

from __future__ import annotations

from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Static


class StatusBar(Static):
    """Top status bar showing connection, task, and elapsed time."""

    connection: reactive[str] = reactive("Disconnected")
    task_info: reactive[str] = reactive("")
    elapsed: reactive[str] = reactive("0:00")

    def render(self) -> str:
        conn_icon = "●" if "Connected" in self.connection else "○"
        parts = [f"{conn_icon} {self.connection}"]
        if self.task_info:
            parts.append(self.task_info)
        parts.append(self.elapsed)
        return "  │  ".join(parts)
