"""MonitorDisplay — 4-panel Mission Control TUI.

Long-lived Rich Live display for ``defined monitor``. Shows:
  - Header: robot identity + connection status
  - Current Mission: step tracker + progress bar
  - Points of Interest: POI table from blackboard
  - Reports: recent report-verb messages
  - History: completed missions this session

Usage:
    from defined_cli.mission.controller import MissionController
    from defined_cli.tui.monitor import MonitorDisplay

    display = MonitorDisplay(controller)
    display.run(launch_fn=lambda: controller.launch_mission(...))
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from datetime import datetime

from rich.columns import Columns
from rich.console import Console, Group, RenderableType
from rich.live import Live
from rich.panel import Panel
from rich.progress import BarColumn, Progress, TaskID, TextColumn
from rich.table import Table
from rich.text import Text

from defined_cli.state.model import RobotStatus
from defined_cli.tui.app import StepState, StepTracker
from defined_cli.transport import TaskProgress

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from defined_cli.mission.controller import MissionController


# Status → color mapping for the header
_STATUS_COLOR: dict[RobotStatus, str] = {
    RobotStatus.OFFLINE: "dim",
    RobotStatus.IDLE: "yellow",
    RobotStatus.ON_MISSION: "green",
    RobotStatus.PAUSED: "cyan",
}


class MonitorDisplay:
    """4-panel Mission Control TUI backed by Rich Live at 4Hz.

    Reads state from ``MissionController`` properties — never writes.
    Thread-safe: the render loop only reads, callbacks only write to
    controller (which is internally locked).

    Args:
        controller: MissionController instance to read state from.
    """

    def __init__(self, controller: MissionController) -> None:
        self._controller = controller
        self._done = threading.Event()
        self._launched = False
        self._tracker: StepTracker | None = None
        self._last_steps: list = []

    # ------------------------------------------------------------------
    # Renderable construction
    # ------------------------------------------------------------------

    def build_renderable(self) -> RenderableType:
        """Build the full 4-panel layout from current controller state."""
        ctrl = self._controller

        # Sync step tracker with controller steps
        steps = ctrl.steps
        if steps != self._last_steps:
            self._tracker = StepTracker(steps)
            self._last_steps = steps
        if self._tracker is not None:
            progress = ctrl.step_progress
            if progress is not None:
                self._tracker.update(progress)

        header = self._build_header()
        panel_mission = self._build_mission_panel()
        panel_pois = self._build_poi_panel()
        panel_reports = self._build_reports_panel()
        panel_history = self._build_history_panel()

        top_row = Columns([panel_mission, panel_pois], equal=True)
        bottom_row = Columns([panel_reports, panel_history], equal=True)
        return Group(header, top_row, bottom_row)

    def _build_header(self) -> RenderableType:
        status = self._controller.robot_status
        color = _STATUS_COLOR.get(status, "white")
        title = Text()
        title.append("DEFINED MISSION CONTROL", style="bold white")
        title.append("  ●  ", style="dim")
        title.append(status.value, style=f"bold {color}")
        err = self._controller.last_error
        if err:
            title.append(f"  ✗ {err[:60]}", style="red")
        from rich.rule import Rule
        return Rule(title=title)

    def _build_mission_panel(self) -> RenderableType:
        ctrl = self._controller
        mission = ctrl.current_mission
        progress = ctrl.step_progress

        lines: list[RenderableType] = []

        if mission is None:
            lines.append(Text("No active mission", style="dim"))
        else:
            # Mission name + status
            name_line = Text()
            name_line.append(mission.task_name, style="bold cyan")
            name_line.append("  ")
            status_color = "green" if mission.status == "SUCCESS" else (
                "red" if mission.status == "FAILURE" else "yellow"
            )
            name_line.append(mission.status, style=status_color)
            lines.append(name_line)

        # Step tracker table
        if self._tracker is not None and self._tracker.steps:
            table = Table.grid(padding=(0, 1))
            table.add_column(width=2)
            table.add_column()
            table.add_column(justify="right", style="dim", width=6)
            for i, step in enumerate(self._tracker.steps):
                states = self._tracker.get_states()
                state = states[i] if i < len(states) else StepState.PENDING
                elapsed = self._tracker.elapsed_for(i)
                elapsed_str = f"{elapsed:.1f}s" if elapsed is not None else ""
                table.add_row(
                    Text(state.icon, style=state.color),
                    Text(step.label, style=state.color),
                    elapsed_str,
                )
            lines.append(table)

        # Progress bar
        if progress is not None:
            pct = progress.progress
            filled = int(pct / 5)
            bar = "█" * filled + "░" * (20 - filled)
            pct_line = Text()
            pct_line.append(f"[{bar}] ", style="green")
            pct_line.append(f"{pct}%", style="bold")
            lines.append(pct_line)

        return Panel(Group(*lines), title="Current Mission", border_style="cyan", padding=(0, 1))

    def _build_poi_panel(self) -> RenderableType:
        pois = self._controller.pois
        if not pois:
            content = Text("No POIs defined.\ndefined world add <name> <x> <y>", style="dim")
            return Panel(content, title="Points of Interest", border_style="blue", padding=(0, 1))

        table = Table(show_header=True, header_style="bold blue", box=None, padding=(0, 1))
        table.add_column("Name", style="cyan")
        table.add_column("X", justify="right")
        table.add_column("Y", justify="right")
        table.add_column("Type", style="dim")

        for name, poi in pois.items():
            center = poi.get("center", {})
            poi_type = poi.get("type", "static")
            type_color = "dim" if poi_type == "static" else (
                "yellow" if poi_type == "constant" else "magenta"
            )
            table.add_row(
                name,
                str(round(center.get("x", 0.0), 2)),
                str(round(center.get("y", 0.0), 2)),
                Text(poi_type, style=type_color),
            )

        return Panel(table, title="Points of Interest", border_style="blue", padding=(0, 1))

    def _build_reports_panel(self) -> RenderableType:
        reports = self._controller.reports
        if not reports:
            content = Text("No reports yet.", style="dim")
        else:
            lines = []
            for msg in reports[-10:]:
                lines.append(Text(f"  {msg}", style="white"))
            content = Group(*lines)
        return Panel(content, title="Reports", border_style="magenta", padding=(0, 1))

    def _build_history_panel(self) -> RenderableType:
        history = self._controller.mission_history
        if not history:
            content = Text("No completed missions.", style="dim")
            return Panel(content, title="History", border_style="yellow", padding=(0, 1))

        table = Table(show_header=True, header_style="bold yellow", box=None, padding=(0, 1))
        table.add_column("Mission", style="cyan")
        table.add_column("Result")
        table.add_column("Completed", style="dim")

        for record in reversed(history[-8:]):
            color = "green" if record.status == "SUCCESS" else "red"
            completed = ""
            if record.completed_at:
                try:
                    dt = datetime.fromisoformat(record.completed_at)
                    completed = dt.strftime("%H:%M:%S")
                except ValueError:
                    completed = record.completed_at[:19]
            table.add_row(
                record.task_name,
                Text(record.status, style=color),
                completed,
            )

        return Panel(table, title="History", border_style="yellow", padding=(0, 1))

    # ------------------------------------------------------------------
    # Run loop
    # ------------------------------------------------------------------

    def run(self, launch_fn: Callable[[], None] | None = None) -> None:
        """Connect controller, optionally auto-launch a task, run TUI.

        Blocks until the task completes (if ``launch_fn`` given) or
        until Ctrl-C. Disconnects the controller on exit.

        Args:
            launch_fn: Zero-arg callable that launches a mission.
                Called 0.5s after TUI renders first frame.
        """
        try:
            self._controller.connect()
        except Exception as exc:
            # Connection failed — show OFFLINE state, don't crash
            pass

        if launch_fn is not None:
            def _launch_worker() -> None:
                time.sleep(0.5)
                try:
                    launch_fn()
                except Exception:
                    pass
                self._launched = True

            threading.Thread(target=_launch_worker, daemon=True).start()

        console = Console(stderr=True)
        try:
            with Live(
                self.build_renderable(),
                console=console,
                refresh_per_second=4,
                screen=True,
            ) as live:
                while not self._done.is_set():
                    live.update(self.build_renderable())

                    # Auto-exit after single task completes
                    if (
                        self._launched
                        and not self._controller.is_mission_running
                        and self._controller.robot_status in (RobotStatus.IDLE, RobotStatus.OFFLINE)
                    ):
                        # Give the user 2 seconds to see the final state
                        time.sleep(2.0)
                        live.update(self.build_renderable())
                        break

                    # Attempt reconnect if transport dropped (not mid-mission)
                    if (
                        not self._controller._transport.is_connected
                        and not self._controller.is_mission_running
                        and self._controller.robot_status != RobotStatus.OFFLINE
                    ):
                        self._controller.reconnect(max_retries=3, delay=2.0)

                    self._done.wait(timeout=0.25)

        except KeyboardInterrupt:
            pass
        finally:
            self._controller.disconnect()
