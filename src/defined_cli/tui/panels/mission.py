"""Mission panel — step tracker with icons and progress."""

from __future__ import annotations

from typing import TYPE_CHECKING

from defined_cli.tui.panels.base import BasePanel, register_panel

if TYPE_CHECKING:
    from defined_cli.mission.events import SessionEvent
    from defined_cli.mission.session import DefinedSession


@register_panel
class MissionPanel(BasePanel):
    """Displays mission steps with status icons and progress bar."""

    PANEL_TITLE = "MISSION"
    PANEL_ID = "panel-mission"

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._steps: list[tuple[str, str, str]] = []  # (icon, label, status)
        self._progress: int = 0
        self._task_name: str = ""

    def update_steps(self, steps: list[tuple[str, str, str]], progress: int, task_name: str = "") -> None:
        """Directly set step data (useful for testing and non-session use)."""
        self._steps = steps
        self._progress = progress
        self._task_name = task_name
        self.refresh()

    def clear_mission(self) -> None:
        """Clear all mission data."""
        self._steps = []
        self._progress = 0
        self._task_name = ""
        self.refresh()

    def on_tick(self, session: DefinedSession) -> None:
        steps = session.steps
        progress = session.current_progress
        last = session.last_mission

        if not steps:
            if self._steps:
                self._steps = []
                self._progress = 0
                self._task_name = ""
                self.refresh()
            return

        step_data = []
        for i, step in enumerate(steps):
            if progress is None:
                icon, status = "○", "PENDING"
            elif i < progress.current:
                icon, status = "✓", "SUCCESS"
            elif i == progress.current:
                if progress.status == "SUCCESS" and progress.current == progress.total - 1:
                    icon, status = "✓", "SUCCESS"
                elif progress.status == "FAILURE":
                    icon, status = "✗", "FAILURE"
                else:
                    icon, status = "⟳", "RUNNING"
            else:
                icon, status = "○", "PENDING"
            step_data.append((icon, step.label, status))

        pct = progress.progress if progress else 0
        task_name = last.task_name if last else ""
        self._steps = step_data
        self._progress = pct
        self._task_name = task_name
        self.refresh()

    def render(self) -> str:
        if not self._steps:
            return "[dim]No active mission.\nType /run <task> to start.[/dim]"

        lines = []
        if self._task_name:
            lines.append(f"[bold cyan]{self._task_name}[/bold cyan]")
            lines.append("")

        is_running = any(s == "RUNNING" for _, _, s in self._steps)

        for icon, label, status in self._steps:
            color = {"RUNNING": "cyan", "SUCCESS": "green", "FAILURE": "red"}.get(status, "dim")
            lines.append(f"[{color}]{icon} {label}[/{color}]")

        # Progress indicator
        lines.append("")
        if is_running and self._progress == 0:
            lines.append("[cyan]⟳ Running...[/cyan]")
        elif self._progress > 0:
            filled = self._progress // 5
            bar = "▓" * filled + "░" * (20 - filled)
            lines.append(f"[cyan]{bar} {self._progress}%[/cyan]")

        return "\n".join(lines)
