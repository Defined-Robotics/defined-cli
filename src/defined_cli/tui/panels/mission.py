"""Mission panel — step tracker with icons and progress."""

from __future__ import annotations

from textual.widgets import Static


class MissionPanel(Static):
    """Displays mission steps with status icons and progress bar."""

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._steps: list[tuple[str, str, str]] = []  # (icon, label, status)
        self._progress: int = 0
        self._task_name: str = ""

    def update_steps(self, steps: list[tuple[str, str, str]], progress: int, task_name: str = "") -> None:
        self._steps = steps
        self._progress = progress
        self._task_name = task_name
        self.refresh()

    def clear_mission(self) -> None:
        self._steps = []
        self._progress = 0
        self._task_name = ""
        self.refresh()

    def render(self) -> str:
        if not self._steps:
            return "[dim]No active mission. Type /run <task> to start.[/dim]"

        lines = []
        if self._task_name:
            lines.append(f"[bold cyan]{self._task_name}[/bold cyan]")
            lines.append("")

        for icon, label, status in self._steps:
            color = {"RUNNING": "cyan", "SUCCESS": "green", "FAILURE": "red"}.get(status, "dim")
            lines.append(f"[{color}]{icon} {label}[/{color}]")

        # Progress bar
        if self._progress > 0:
            filled = self._progress // 5
            bar = "▓" * filled + "░" * (20 - filled)
            lines.append("")
            lines.append(f"[cyan]{bar} {self._progress}%[/cyan]")

        return "\n".join(lines)
