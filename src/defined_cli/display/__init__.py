"""Display protocol — how the CLI shows progress to the user.

A display handles rendering pipeline phases, task execution
progress, errors, and completion status.

The default implementation is ``RichDisplay`` (Session 3) which uses
the ``rich`` library for formatted console output.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from defined_cli.errors import DefinedError
from defined_cli.transport import TaskProgress

if TYPE_CHECKING:
    from defined_cli.compiler import StepInfo


class DisplayBase(ABC):
    """Abstract base for progress/status rendering."""

    @abstractmethod
    def set_steps(self, steps: list[StepInfo]) -> None:
        """Provide the full task step list (called after compile, before monitor)."""

    @abstractmethod
    def show_phase(self, phase: str, message: str) -> None:
        """Show a pipeline phase (e.g. 'Compiling', 'Deploying')."""

    @abstractmethod
    def show_progress(self, progress: TaskProgress) -> None:
        """Render a task execution progress update."""

    @abstractmethod
    def show_error(self, error: DefinedError) -> None:
        """Render an error with suggestion and optional detail."""

    @abstractmethod
    def show_success(self, message: str) -> None:
        """Render a success message."""

    def show_log(self, message: str) -> None:
        """Append a log line. Default: no-op."""

    def show_metadata(
        self,
        task_file: str = "",
        target: str = "",
        host: str = "",
        port: int = 0,
    ) -> None:
        """Show task metadata. Default: no-op."""
