"""Rich-based console display for the Defined CLI."""

from __future__ import annotations

from typing import TYPE_CHECKING

from rich.console import Console

from defined_cli.display import DisplayBase
from defined_cli.errors import DefinedError
from defined_cli.transport import TaskProgress

if TYPE_CHECKING:
    from defined_cli.compiler import StepInfo


class RichDisplay(DisplayBase):
    """Renders pipeline phases and task progress using Rich."""

    def __init__(self, console: Console | None = None) -> None:
        self._console = console or Console(stderr=True)
        self._steps: list[StepInfo] = []

    def set_steps(self, steps: list[StepInfo]) -> None:
        self._steps = list(steps)
        for step in self._steps:
            self._console.print(f"  [dim]{step.index + 1}. {step.label}[/]")

    def show_phase(self, phase: str, message: str) -> None:
        self._console.print(f"[bold blue]●[/] [bold]{phase}[/] {message}")

    def show_progress(self, progress: TaskProgress) -> None:
        filled = progress.progress // 5
        bar = "█" * filled + "░" * (20 - filled)
        color = {"RUNNING": "cyan", "SUCCESS": "green", "FAILURE": "red"}.get(
            progress.status, "white"
        )
        self._console.print(
            f"  [{color}]{progress.step}[/] [{bar}] {progress.progress}% "
            f"({progress.current}/{progress.total})"
        )

    def show_error(self, error: DefinedError) -> None:
        self._console.print(f"[bold red]✗ {error.message}[/]")
        if error.suggestion:
            self._console.print(f"[yellow]  → {error.suggestion}[/]")

    def show_success(self, message: str) -> None:
        self._console.print(f"[bold green]✓ {message}[/]")
