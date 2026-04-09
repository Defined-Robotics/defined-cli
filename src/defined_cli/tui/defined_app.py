"""DefinedApp — unified Textual TUI for Defined Robotics.

Full-screen app with command bar, 3 panels (mission, world, diagnostics),
and status bar. Reads all state from DefinedSession — no business logic here.

Usage:
    from defined_cli.tui.defined_app import DefinedApp
    app = DefinedApp(session)
    app.run()
"""

from __future__ import annotations

import glob
import time
import threading
from pathlib import Path
from typing import TYPE_CHECKING

from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import Footer, Header, Input, Static

from defined_cli.mission.events import (
    ConnectionStatus,
    MissionStatus,
    SessionEvent,
)
from defined_cli.tui.command_bar import CommandKind, parse_command
from defined_cli.tui.panels.diagnostics import DiagnosticsPanel
from defined_cli.tui.panels.mission import MissionPanel
from defined_cli.tui.panels.status_bar import StatusBar
from defined_cli.tui.panels.world import WorldPanel

if TYPE_CHECKING:
    from defined_cli.mission.session import DefinedSession


_HELP_TEXT = """\
[bold]Commands:[/bold]
  /run <task>          Run a task (fuzzy-match *.task.yaml)
  /stop                Stop current mission
  /restart             Re-run last mission
  /world add <n> <x> <y>  Add a POI
  /world list          Show POIs
  /world mark <name>   Mark robot position as POI
  /status              System health
  /help                This help
  /quit                Exit

[bold]Keyboard:[/bold]
  1-3    Switch panel focus
  d/D    Cycle diagnostics detail
  /      Focus command bar
  q      Quit
"""


class DefinedApp(App):
    """Unified TUI for Defined Robotics."""

    CSS = """
    StatusBar {
        dock: top;
        height: 1;
        background: $primary-background;
        color: $text;
        padding: 0 1;
    }

    #main-area {
        height: 1fr;
    }

    #panel-mission {
        width: 1fr;
        border: solid $primary;
        padding: 0 1;
    }

    #panel-world {
        width: 1fr;
        border: solid $accent;
        padding: 0 1;
    }

    #panel-diagnostics {
        width: 1fr;
        border: solid $warning;
        padding: 0 1;
    }

    #command-input {
        dock: bottom;
        height: 1;
    }

    #feedback-line {
        dock: bottom;
        height: 1;
        color: $text-muted;
        padding: 0 1;
    }

    .panel-title {
        text-style: bold;
        padding: 0 0 1 0;
    }
    """

    BINDINGS = [
        Binding("1", "focus_panel(1)", "Mission", show=False),
        Binding("2", "focus_panel(2)", "World", show=False),
        Binding("3", "focus_panel(3)", "Diagnostics", show=False),
        Binding("d", "cycle_detail", "Detail+", show=False),
        Binding("shift+d", "cycle_detail", "Detail++", show=False),
        Binding("slash", "focus_command", "/Command", show=False),
        Binding("q", "quit_app", "Quit", show=False),
    ]

    def __init__(self, session: DefinedSession, rdf: Path | None = None, **kwargs) -> None:
        super().__init__(**kwargs)
        self._session = session
        self._rdf = rdf
        self._start_time = time.monotonic()
        self._task_dir = Path.cwd()

    def compose(self) -> ComposeResult:
        yield StatusBar(id="status-bar")
        with Horizontal(id="main-area"):
            yield MissionPanel(id="panel-mission")
            yield WorldPanel(id="panel-world")
            yield DiagnosticsPanel(id="panel-diagnostics")
        yield Static("", id="feedback-line")
        yield Input(placeholder="Type / for commands, /help for list", id="command-input")

    def on_mount(self) -> None:
        self._session.add_listener(self._on_session_event)
        self._refresh_timer = self.set_interval(0.25, self._tick)
        # Show welcome if no mission history
        if self._session.last_mission is None:
            self._show_feedback(
                "Welcome to Defined Robotics! Type /run <task> to start. /help for commands."
            )
        self._update_world_panel()

    def on_unmount(self) -> None:
        self._session.remove_listener(self._on_session_event)

    # ------------------------------------------------------------------
    # Session event handler (called from any thread)
    # ------------------------------------------------------------------

    def _on_session_event(self, event: SessionEvent) -> None:
        """Handle session events — marshalled to Textual's event loop."""
        self.call_from_thread(self._handle_event, event)

    def _handle_event(self, event: SessionEvent) -> None:
        diag = self.query_one("#panel-diagnostics", DiagnosticsPanel)
        diag.add_event(event)

        if event.category == "executor":
            self._update_mission_panel()

    # ------------------------------------------------------------------
    # Periodic tick — update status bar and mission panel
    # ------------------------------------------------------------------

    def _tick(self) -> None:
        status_bar = self.query_one("#status-bar", StatusBar)

        # Connection
        conn = self._session.connection_status
        status_bar.connection = conn.value.title()

        # Task info
        mission = self._session.mission_status
        progress = self._session.current_progress
        if mission in (MissionStatus.COMPILING, MissionStatus.DEPLOYING, MissionStatus.RUNNING):
            last = self._session.last_mission
            name = last.task_name if last else "?"
            pct = progress.progress if progress else 0
            filled = pct // 5
            bar = "▓" * filled + "░" * (20 - filled)
            status_bar.task_info = f"Task: {name} ({bar} {pct}%)"
        elif mission == MissionStatus.SUCCEEDED:
            status_bar.task_info = "Task: completed ✓"
        elif mission == MissionStatus.FAILED:
            err = self._session.last_error or "failed"
            status_bar.task_info = f"Task: {err[:40]} ✗"
        else:
            status_bar.task_info = ""

        # Elapsed
        elapsed = int(time.monotonic() - self._start_time)
        mins, secs = divmod(elapsed, 60)
        status_bar.elapsed = f"{mins}m{secs:02d}s"

        # Update mission panel
        self._update_mission_panel()

    def _update_mission_panel(self) -> None:
        panel = self.query_one("#panel-mission", MissionPanel)
        steps = self._session.steps
        progress = self._session.current_progress
        last = self._session.last_mission

        if not steps:
            panel.clear_mission()
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
        panel.update_steps(step_data, pct, task_name)

    def _update_world_panel(self) -> None:
        panel = self.query_one("#panel-world", WorldPanel)
        panel.update_pois(self._session.list_pois())

    # ------------------------------------------------------------------
    # Command input
    # ------------------------------------------------------------------

    @on(Input.Submitted, "#command-input")
    def on_command_submitted(self, event: Input.Submitted) -> None:
        raw = event.value.strip()
        event.input.value = ""

        if not raw:
            return

        cmd = parse_command(raw)
        self._execute_command(cmd)

    def _execute_command(self, cmd) -> None:
        if cmd.kind == CommandKind.UNKNOWN:
            self._show_feedback(f"[red]{cmd.error}[/red]")
            return

        if cmd.kind == CommandKind.HELP:
            self._show_feedback(_HELP_TEXT)
            return

        if cmd.kind == CommandKind.QUIT:
            if self._session.mission_status in (
                MissionStatus.COMPILING, MissionStatus.DEPLOYING, MissionStatus.RUNNING,
            ):
                self._show_feedback("[yellow]Mission running. /stop first, then /quit.[/yellow]")
                return
            self.exit()
            return

        if cmd.kind == CommandKind.STATUS:
            conn = self._session.connection_status.value
            mission = self._session.mission_status.value
            pois = len(self._session.list_pois())
            self._show_feedback(f"Connection: {conn} | Mission: {mission} | POIs: {pois}")
            return

        if cmd.kind == CommandKind.RUN:
            self._run_task(cmd.args[0])
            return

        if cmd.kind == CommandKind.STOP:
            self._session.stop_mission()
            self._show_feedback("Mission stopped.")
            return

        if cmd.kind == CommandKind.RESTART:
            try:
                self._session.restart_mission()
                self._show_feedback("Restarting last mission...")
            except RuntimeError as exc:
                self._show_feedback(f"[red]{exc}[/red]")
            return

        if cmd.kind == CommandKind.WORLD_ADD:
            name, x_str, y_str = cmd.args
            try:
                x, y = float(x_str), float(y_str)
            except ValueError:
                self._show_feedback("[red]Coordinates must be numbers.[/red]")
                return
            self._session.add_poi(name, x, y)
            self._update_world_panel()
            self._show_feedback(f"Added POI '{name}' at ({x}, {y})")
            return

        if cmd.kind == CommandKind.WORLD_LIST:
            pois = self._session.list_pois()
            if not pois:
                self._show_feedback("No POIs defined.")
            else:
                lines = [f"  {name}: ({p['center']['x']:.1f}, {p['center']['y']:.1f})" for name, p in pois.items()]
                self._show_feedback("POIs:\n" + "\n".join(lines))
            return

        if cmd.kind == CommandKind.WORLD_MARK:
            try:
                x, y = self._session.mark_poi(cmd.args[0])
                self._update_world_panel()
                self._show_feedback(f"Marked '{cmd.args[0]}' at ({x:.2f}, {y:.2f})")
            except Exception as exc:
                self._show_feedback(f"[red]Mark failed: {exc}[/red]")
            return

    def _run_task(self, name: str) -> None:
        """Find a matching task file and run it."""
        if self._rdf is None:
            self._show_feedback("[red]No RDF file specified. Use --rdf flag.[/red]")
            return

        # Fuzzy match *.task.yaml
        pattern = str(self._task_dir / "**" / f"*{name}*.task.yaml")
        matches = glob.glob(pattern, recursive=True)
        if not matches:
            self._show_feedback(f"[red]No task file matching '{name}' found.[/red]")
            return

        task_path = Path(matches[0])
        if len(matches) > 1:
            names = [Path(m).stem for m in matches[:5]]
            self._show_feedback(f"Multiple matches: {names}. Using {task_path.name}")

        try:
            self._session.run_mission(task_path, self._rdf)
            self._show_feedback(f"Running {task_path.name}...")
        except RuntimeError as exc:
            self._show_feedback(f"[red]{exc}[/red]")

    def _show_feedback(self, text: str) -> None:
        feedback = self.query_one("#feedback-line", Static)
        feedback.update(text)

    # ------------------------------------------------------------------
    # Key bindings
    # ------------------------------------------------------------------

    def action_focus_panel(self, panel_num: int) -> None:
        panel_ids = {1: "#panel-mission", 2: "#panel-world", 3: "#panel-diagnostics"}
        panel_id = panel_ids.get(panel_num)
        if panel_id:
            self.query_one(panel_id).focus()

    def action_cycle_detail(self) -> None:
        diag = self.query_one("#panel-diagnostics", DiagnosticsPanel)
        diag.cycle_detail()

    def action_focus_command(self) -> None:
        self.query_one("#command-input", Input).focus()

    def action_quit_app(self) -> None:
        cmd = parse_command("/quit")
        self._execute_command(cmd)
