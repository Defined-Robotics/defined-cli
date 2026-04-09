"""DefinedApp — unified Textual TUI for Defined Robotics.

Full-screen app with command bar, three data panels (mission, world,
diagnostics), and a status bar.  All business logic lives in
``DefinedSession``; this module contains only rendering and input handling.

Layout
------
┌──────────────────────────────────────────────────────┐
│  status bar  (connection · task info · elapsed)      │
├──────────────┬───────────────┬───────────────────────┤
│   Mission    │     World     │     Diagnostics       │
│   (steps,    │   (POI list)  │   (event log,         │
│   progress)  │               │    detail levels)     │
├──────────────┴───────────────┴───────────────────────┤
│  feedback line  (one-line command output)            │
│  command input  (slash commands)                     │
└──────────────────────────────────────────────────────┘

Slash commands (type in command input)
---------------------------------------
/run <task>          Compile and run a task (fuzzy-match *.task.yaml).
/stop                Stop the current mission.
/restart             Re-run the last mission.
/teleop              Toggle manual-control mode (arrow keys + space).
/estop  or  !!       Emergency stop — zero velocity + mission abort.
/detail              Cycle diagnostics panel detail level.
/world add/list/mark Manage Points of Interest.
/status              Print health summary.
/help                Show full help.
/quit                Exit (blocked while a mission is running).

Keyboard shortcuts
------------------
Escape    Return focus to command input / exit teleop mode.
Ctrl+E    Emergency stop (priority binding — works even while typing).
Ctrl+Q    Quit.
Arrow keys / Space  Move robot (teleop mode only).

Usage:
    from defined_cli.tui.defined_app import DefinedApp
    app = DefinedApp(session, rdf=Path("robot.rdf.yaml"))
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
from textual.events import Key
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
from defined_cli.tui.panels.teleop import TelePanel
from defined_cli.tui.panels.world import WorldPanel

if TYPE_CHECKING:
    from defined_cli.mission.session import DefinedSession


_HELP_TEXT = """\
[bold]Commands:[/bold]
  /run <task> [k=v]    Run a task (fuzzy-match *.task.yaml), optional param overrides
  /stop                Stop current mission
  /restart             Re-run last mission
  /world add <n> <x> <y>  Add a POI
  /world list          Show POIs
  /world mark <name>   Mark robot position as POI
  /teleop              Toggle manual control (arrow keys move, space stops)
  /detail              Cycle diagnostics detail level (Summary → Suggestions → Advanced)
  /estop  or  !!       Emergency stop — halt motion and abort mission
  /status              System health
  /help                This help
  /quit                Exit

[bold]Keyboard:[/bold]
  Escape      Focus command bar / exit teleop
  Ctrl+E      Emergency stop (works in any mode, even while typing)
  Ctrl+Q      Quit
  Arrow keys  Move robot (teleop mode only)
  Space       Stop robot (teleop mode only)
"""

# Velocity constants for TurtleBot3 Burger
_TELEOP_LINEAR = 0.2   # m/s
_TELEOP_ANGULAR = 0.5  # rad/s


class DefinedApp(App):
    """Unified TUI for Defined Robotics."""

    CSS = """
    #status-bar {
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

    #panel-teleop {
        width: 1fr;
        border: solid $error;
        padding: 0 1;
        display: none;
    }

    #panel-teleop.active {
        display: block;
    }

    #feedback-line {
        height: auto;
        max-height: 14;
        color: $text-muted;
        padding: 0 1;
    }

    #command-input {
        height: 3;
    }
    """

    BINDINGS = [
        Binding("escape", "focus_command", "Command bar", show=False),
        Binding("ctrl+q", "quit_app", "Quit", show=False),
        # priority=True so ctrl+e fires even when the command input is focused
        Binding("ctrl+e", "emergency_stop", "E-STOP", show=True, priority=True),
    ]

    def __init__(self, session: DefinedSession, rdf: Path | None = None, **kwargs) -> None:
        super().__init__(**kwargs)
        self._session = session
        self._rdf = rdf
        self._start_time = time.monotonic()
        self._task_dir = Path.cwd()
        self._teleop_mode = False
        self._teleop_stop_handle: object | None = None  # pending auto-stop timer

    def compose(self) -> ComposeResult:
        with Vertical():
            yield StatusBar(id="status-bar")
            with Horizontal(id="main-area"):
                yield MissionPanel(id="panel-mission")
                yield WorldPanel(id="panel-world")
                yield DiagnosticsPanel(id="panel-diagnostics")
                yield TelePanel(id="panel-teleop")
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
        # Auto-focus the command input so users can type immediately
        self.query_one("#command-input", Input).focus()
        # Connect in the background so the TUI appears immediately
        self._connect_background()

    @work(thread=True)
    def _connect_background(self) -> None:
        """Connect to transport in a worker thread — TUI stays responsive."""
        try:
            self._session.connect()
        except Exception:
            pass  # status bar will show Disconnected

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

        # Teleop mode overrides task info
        if self._teleop_mode:
            status_bar.task_info = "[bold red]TELEOP[/bold red] ↑↓←→ move  space=stop  esc=exit"
        else:
            # Task info
            mission = self._session.mission_status
            progress = self._session.current_progress
            if mission in (MissionStatus.COMPILING, MissionStatus.DEPLOYING, MissionStatus.RUNNING):
                last = self._session.last_mission
                name = last.task_name if last else "?"
                pct = progress.progress if progress else 0
                if pct > 0:
                    filled = pct // 5
                    bar = "▓" * filled + "░" * (20 - filled)
                    status_bar.task_info = f"Task: {name} ({bar} {pct}%)"
                else:
                    status_bar.task_info = f"Task: {name} (running...)"
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
            self._run_task(cmd.args[0], cmd.kwargs)
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

        if cmd.kind == CommandKind.DETAIL:
            diag = self.query_one("#panel-diagnostics", DiagnosticsPanel)
            diag.cycle_detail()
            level = {1: "Summary", 2: "Suggestions", 3: "Advanced"}.get(diag._detail_level, "")
            self._show_feedback(f"Diagnostics detail: {level}")
            return

        if cmd.kind == CommandKind.TELEOP:
            self._toggle_teleop()
            return

        if cmd.kind == CommandKind.ESTOP:
            self.action_emergency_stop()
            return

    def action_emergency_stop(self) -> None:
        """Emergency stop: halt motion, abort mission, and exit teleop mode."""
        self._teleop_mode = False
        tele = self.query_one("#panel-teleop", TelePanel)
        tele.remove_class("active")
        tele.update_velocity(0.0, 0.0)
        tele.set_active_direction(None)
        self._session.emergency_stop()
        self._show_feedback("[bold red]⛔ EMERGENCY STOP — robot halted[/bold red]")
        self.query_one("#command-input", Input).focus()

    def _toggle_teleop(self) -> None:
        """Enter or exit teleop mode, showing or hiding the TelePanel."""
        self._teleop_mode = not self._teleop_mode
        tele = self.query_one("#panel-teleop", TelePanel)
        if self._teleop_mode:
            tele.add_class("active")
            tele.update_velocity(0.0, 0.0)
            tele.set_active_direction(None)
            # Blur command input so arrow keys bubble to on_key
            self.set_focus(None)
            self._show_feedback(
                "[yellow]Teleop ON — arrows=move, space=stop, Escape or /teleop to exit[/yellow]"
            )
        else:
            tele.remove_class("active")
            self._send_teleop_stop()
            self.query_one("#command-input", Input).focus()
            self._show_feedback("Teleop OFF.")

    def _send_velocity(self, linear_x: float, angular_z: float, direction: str | None = None) -> None:
        """Publish velocity, update TelePanel display, and schedule auto-stop."""
        self._session.publish_velocity(linear_x, angular_z)
        if self._teleop_mode:
            tele = self.query_one("#panel-teleop", TelePanel)
            tele.update_velocity(linear_x, angular_z)
            tele.set_active_direction(direction)
        # Cancel previous auto-stop and schedule a new one
        if self._teleop_stop_handle is not None:
            try:
                self._teleop_stop_handle.stop()
            except Exception:
                pass
        self._teleop_stop_handle = self.set_timer(0.6, self._send_teleop_stop)

    def _send_teleop_stop(self) -> None:
        """Publish zero velocity and clear active direction in TelePanel."""
        self._session.publish_velocity(0.0, 0.0)
        if self._teleop_mode:
            tele = self.query_one("#panel-teleop", TelePanel)
            tele.update_velocity(0.0, 0.0)
            tele.set_active_direction(None)

    def on_key(self, event: Key) -> None:
        """Handle arrow keys and space in teleop mode."""
        if not self._teleop_mode:
            return
        key = event.key
        if key == "up":
            self._send_velocity(_TELEOP_LINEAR, 0.0, "forward")
            event.stop()
        elif key == "down":
            self._send_velocity(-_TELEOP_LINEAR, 0.0, "backward")
            event.stop()
        elif key == "left":
            self._send_velocity(0.0, _TELEOP_ANGULAR, "left")
            event.stop()
        elif key == "right":
            self._send_velocity(0.0, -_TELEOP_ANGULAR, "right")
            event.stop()
        elif key == "space":
            self._send_teleop_stop()
            event.stop()

    def _run_task(self, name: str, param_overrides: dict[str, str] | None = None) -> None:
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
            self._session.run_mission(task_path, self._rdf, param_overrides=param_overrides or None)
            suffix = f" ({', '.join(f'{k}={v}' for k, v in param_overrides.items())})" if param_overrides else ""
            self._show_feedback(f"Running {task_path.name}{suffix}...")
        except RuntimeError as exc:
            self._show_feedback(f"[red]{exc}[/red]")

    def _show_feedback(self, text: str) -> None:
        feedback = self.query_one("#feedback-line", Static)
        feedback.update(text)

    # ------------------------------------------------------------------
    # Key bindings
    # ------------------------------------------------------------------

    def action_focus_command(self) -> None:
        if self._teleop_mode:
            self._teleop_mode = False
            self._send_teleop_stop()
            self._show_feedback("Teleop OFF.")
        self.query_one("#command-input", Input).focus()

    def action_quit_app(self) -> None:
        cmd = parse_command("/quit")
        self._execute_command(cmd)
