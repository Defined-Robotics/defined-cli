"""Display protocol — how the CLI shows progress to the user.

A display handles rendering pipeline phases, task execution
progress, errors, and completion status.

The default implementation is ``RichDisplay`` (Session 3) which uses
the ``rich`` library for formatted console output.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from defined_cli.errors import DefinedError
from defined_cli.transport import TaskProgress


class DisplayBase(ABC):
    """Abstract base for progress/status rendering."""

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
