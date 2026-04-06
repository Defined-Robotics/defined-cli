"""TUI display — Rich Live-based task monitor.

Replaces the Textual-based TUI with a lighter Rich Live approach.
The display redraws in-place at 4Hz using Rich renderables.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from collections.abc import Callable
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING

from rich.console import Console, Group, RenderableType
from rich.panel import Panel
from rich.rule import Rule
from rich.table import Table
from rich.text import Text

from defined_cli.display import DisplayBase
from defined_cli.errors import DefinedError
from defined_cli.transport import TaskProgress

if TYPE_CHECKING:
    from defined_cli.compiler import StepInfo


# ---------------------------------------------------------------------------
# Step state tracking (no Rich dependency — testable standalone)
# ---------------------------------------------------------------------------


class StepState(Enum):
    """Visual state of a task step."""

    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"

    @property
    def icon(self) -> str:
        return {
            StepState.PENDING: "○",
            StepState.RUNNING: "▸",
            StepState.SUCCESS: "✓",
            StepState.FAILED: "✗",
        }[self]

    @property
    def color(self) -> str:
        return {
            StepState.PENDING: "dim",
            StepState.RUNNING: "cyan",
            StepState.SUCCESS: "green",
            StepState.FAILED: "red",
        }[self]


class StepTracker:
    """Tracks step states and per-step timing from TaskProgress updates."""

    def __init__(self, steps: list[StepInfo]) -> None:
        self._steps = list(steps)
        self._states = [StepState.PENDING] * len(steps)
        self._start_times: dict[int, float] = {}
        self._end_times: dict[int, float] = {}

    def update(self, progress: TaskProgress) -> None:
        """Update states based on a TaskProgress message."""
        current = progress.current
        now = time.monotonic()

        for i in range(len(self._steps)):
            if i < current:
                if self._states[i] != StepState.SUCCESS:
                    self._states[i] = StepState.SUCCESS
                    if i not in self._start_times:
                        self._start_times[i] = now
                    if i not in self._end_times:
                        self._end_times[i] = now
            elif i == current:
                if i not in self._start_times:
                    self._start_times[i] = now
                if progress.status == "FAILURE":
                    self._states[i] = StepState.FAILED
                    if i not in self._end_times:
                        self._end_times[i] = now
                elif progress.status == "SUCCESS":
                    self._states[i] = StepState.SUCCESS
                    if i not in self._end_times:
                        self._end_times[i] = now
                else:
                    self._states[i] = StepState.RUNNING
            else:
                if self._states[i] not in (StepState.FAILED, StepState.SUCCESS):
                    self._states[i] = StepState.PENDING

    def get_states(self) -> list[StepState]:
        return list(self._states)

    def elapsed_for(self, index: int) -> float | None:
        """Return elapsed seconds for a step, or None if not started."""
        if index not in self._start_times:
            return None
        end = self._end_times.get(index, time.monotonic())
        return end - self._start_times[index]

    @property
    def steps(self) -> list[StepInfo]:
        return self._steps


# ---------------------------------------------------------------------------
# Phase colors
# ---------------------------------------------------------------------------

_PHASE_COLORS: dict[str, str] = {
    "Starting": "blue",
    "Connecting": "yellow",
    "Waiting": "yellow",
    "Warning": "yellow",
    "Compiling": "magenta",
    "Deploying": "cyan",
    "Monitoring": "green",
}


# ---------------------------------------------------------------------------
# Rich Live display
# ---------------------------------------------------------------------------


class LiveDisplay(DisplayBase):
    """Rich Live TUI — redraws in-place using Rich renderables."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._tracker: StepTracker | None = None
        self._phase: str = ""
        self._phase_msg: str = ""
        self._log_lines: deque[str] = deque(maxlen=50)
        self._error: DefinedError | None = None
        self._success_msg: str | None = None
        self._metadata: dict[str, object] = {}
        self._start_time: float = time.monotonic()
        self._progress_pct: int = 0
        self._done = threading.Event()

    # -- DisplayBase implementation ------------------------------------------

    def set_steps(self, steps: list[StepInfo]) -> None:
        with self._lock:
            self._tracker = StepTracker(steps)

    def show_phase(self, phase: str, message: str) -> None:
        with self._lock:
            self._phase = phase
            self._phase_msg = message
            ts = datetime.now().strftime("%H:%M:%S")
            self._log_lines.append(f"{ts}  {phase} {message}")

    def show_progress(self, progress: TaskProgress) -> None:
        with self._lock:
            if self._tracker:
                self._tracker.update(progress)
            self._progress_pct = progress.progress

    def show_error(self, error: DefinedError) -> None:
        with self._lock:
            self._error = error
            ts = datetime.now().strftime("%H:%M:%S")
            self._log_lines.append(f"{ts}  ✗ {error.message}")
        self._done.set()

    def show_success(self, message: str) -> None:
        with self._lock:
            self._success_msg = message
            ts = datetime.now().strftime("%H:%M:%S")
            self._log_lines.append(f"{ts}  ✓ {message}")
        self._done.set()

    def show_log(self, message: str) -> None:
        with self._lock:
            ts = datetime.now().strftime("%H:%M:%S")
            self._log_lines.append(f"{ts}  {message}")

    def show_metadata(
        self,
        task_file: str = "",
        target: str = "",
        host: str = "",
        port: int = 0,
    ) -> None:
        with self._lock:
            self._metadata = {
                "task_file": task_file,
                "target": target,
                "host": host,
                "port": port,
            }

    # -- Renderable ----------------------------------------------------------

    def build_renderable(self) -> RenderableType:
        """Build the full display as a Rich Group of renderables."""
        with self._lock:
            parts: list[RenderableType] = []

            # Title
            task_name = self._metadata.get("task_file", "")
            title = Text(f" defined — {task_name}" if task_name else " defined", style="bold")
            parts.append(title)
            parts.append(Rule(style="dim"))

            # Metadata bar
            if self._metadata:
                meta = Text()
                if self._metadata.get("task_file"):
                    meta.append(f" 📁 {self._metadata['task_file']}", style="dim")
                if self._metadata.get("target"):
                    meta.append(f"  🎯 {self._metadata['target']}", style="dim")
                if self._metadata.get("host"):
                    host = self._metadata["host"]
                    port = self._metadata.get("port", "")
                    meta.append(f"  🔗 {host}:{port}", style="dim")
                if meta.plain:
                    parts.append(meta)

            # Phase banner
            if self._phase:
                color = _PHASE_COLORS.get(self._phase, "white")
                phase_text = Text(f" ▶ {self._phase} — {self._phase_msg}", style=f"bold {color}")
                parts.append(phase_text)
                parts.append(Text())  # spacer

            # Steps table
            if self._tracker:
                table = Table(show_header=False, show_edge=False, box=None, padding=(0, 1))
                table.add_column("icon", width=2, no_wrap=True)
                table.add_column("label", min_width=30, no_wrap=True)
                table.add_column("elapsed", width=6, justify="right", no_wrap=True)

                for i, (step, state) in enumerate(
                    zip(self._tracker.steps, self._tracker.get_states())
                ):
                    elapsed = self._tracker.elapsed_for(i)
                    if elapsed is not None:
                        mins, secs = divmod(int(elapsed), 60)
                        elapsed_str = f"{mins}:{secs:02d}"
                    else:
                        elapsed_str = "—"

                    table.add_row(
                        Text(state.icon, style=state.color),
                        Text(step.label, style=state.color),
                        Text(elapsed_str, style="dim"),
                    )

                parts.append(table)
                parts.append(Text())  # spacer

            # Progress bar
            if self._progress_pct > 0 or self._tracker:
                filled = self._progress_pct // 5
                bar = "█" * filled + "░" * (20 - filled)
                bar_text = Text(f" {bar}  {self._progress_pct}%", style="cyan")
                parts.append(bar_text)
                parts.append(Text())  # spacer

            # Log panel
            if self._log_lines:
                log_text = "\n".join(list(self._log_lines)[-8:])
                parts.append(Panel(log_text, title="Log", border_style="dim", expand=True))

            # Result banner
            if self._success_msg:
                elapsed = int(time.monotonic() - self._start_time)
                mins, secs = divmod(elapsed, 60)
                parts.append(Text())
                parts.append(
                    Text(
                        f" ✓ {self._success_msg} ({mins:02d}:{secs:02d})",
                        style="bold green",
                    )
                )
            elif self._error:
                parts.append(Text())
                parts.append(Text(f" ✗ {self._error.message}", style="bold red"))
                if self._error.suggestion:
                    parts.append(Text(f"   → {self._error.suggestion}", style="yellow"))

            # Elapsed timer (bottom)
            if not self._success_msg and not self._error:
                elapsed = int(time.monotonic() - self._start_time)
                mins, secs = divmod(elapsed, 60)
                parts.append(Text(f" ⏱ {mins:02d}:{secs:02d}", style="dim"))

            return Group(*parts)

    # -- Run loop ------------------------------------------------------------

    def run(self, orchestrator_fn: Callable[[], None]) -> None:
        """Start Rich Live display and run orchestrator in a background thread."""
        from rich.live import Live

        self._start_time = time.monotonic()
        error_holder: list[Exception] = []

        def _worker() -> None:
            try:
                orchestrator_fn()
            except Exception as exc:
                error_holder.append(exc)
                if isinstance(exc, DefinedError):
                    self.show_error(exc)
                else:
                    self._done.set()

        thread = threading.Thread(target=_worker, daemon=True)
        thread.start()

        console = Console(stderr=True)
        try:
            with Live(
                self.build_renderable(),
                console=console,
                refresh_per_second=4,
                transient=True,
            ) as live:
                while not self._done.is_set():
                    live.update(self.build_renderable())
                    self._done.wait(timeout=0.25)
                # Final render (non-transient) so result stays on screen
                live.update(self.build_renderable())
        except KeyboardInterrupt:
            pass

        thread.join(timeout=5)

        # Print final state to console since Live was transient
        console.print(self.build_renderable())

        # Re-raise orchestrator errors after Live has cleaned up
        if error_holder:
            exc = error_holder[0]
            if isinstance(exc, DefinedError):
                raise exc
            console.print(f"\n[bold red]✗ {exc}[/]")
            raise SystemExit(1) from exc


# Backward compatibility alias
TuiDisplay = LiveDisplay
