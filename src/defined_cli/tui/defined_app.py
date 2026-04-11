"""DefinedApp — unified Textual TUI for Defined Robotics.

Full-screen app with command bar, four data panels (mission, world,
diagnostics, teleop), an activity log, and a status bar.  All business
logic lives in ``DefinedSession``; this module contains only rendering
and input handling.

Layout
------
┌──────────────────────────────────────────────────────────────┐
│  RobotName   ● Connected   Task: patrol (▓▓▓░░ 60%)   2m31s │
├────────────────────────────┬─────────────────────────────────┤
│   MISSION                  │   DIAGNOSTICS                   │
├────────────────────────────┼─────────────────────────────────┤
│   WORLD                    │   TELEOP                        │
├────────────────────────────┴─────────────────────────────────┤
│  Activity Log (scrollable, timestamped)                       │
├──────────────────────────────────────────────────────────────┤
│  > /command input                                            │
└──────────────────────────────────────────────────────────────┘

Panels are discovered via ``PANEL_REGISTRY`` and receive data through
``on_tick()`` (polled) and ``on_session_event()`` (pushed).

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
Tab       Cycle focus between panels.
Arrow keys / Space  Move robot (teleop mode only).

Usage:
    from defined_cli.tui.defined_app import DefinedApp
    app = DefinedApp(session, rdf=Path("robot.rdf.yaml"))
    app.run()
"""

from __future__ import annotations

import glob
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.events import Key
from textual.widgets import Input, RichLog

from defined_cli.mission.events import (
    ConnectionStatus,
    MissionStatus,
    SessionEvent,
)
from defined_cli.tui.command_bar import CommandKind, parse_command
from defined_cli.tui.panels.base import BasePanel
from defined_cli.tui.panels.diagnostics import DiagnosticsPanel
from defined_cli.tui.panels.mission import MissionPanel
from defined_cli.tui.panels.status_bar import StatusBar
from defined_cli.tui.panels.teleop import TelePanel
from defined_cli.tui.panels.world import WorldPanel

if TYPE_CHECKING:
    from defined_cli.mission.session import DefinedSession

_log = logging.getLogger(__name__)

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
  Tab         Cycle focus between panels
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

    CSS_PATH = "defined_app.tcss"

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

        # Derive robot name from RDF filename
        self._robot_name = rdf.stem.replace(".rdf", "") if rdf else "unknown"
        self._last_activity_msg: str = ""  # dedup consecutive identical log lines
        self._last_event_msg: str = ""  # dedup session events by message content

    def compose(self) -> ComposeResult:
        with Vertical():
            yield StatusBar(id="status-bar")
            with Vertical(id="panel-grid"):
                with Horizontal(classes="panel-row"):
                    yield MissionPanel(id=MissionPanel.PANEL_ID)
                    yield DiagnosticsPanel(id=DiagnosticsPanel.PANEL_ID)
                with Horizontal(classes="panel-row"):
                    yield WorldPanel(id=WorldPanel.PANEL_ID)
                    yield TelePanel(id=TelePanel.PANEL_ID)
            yield RichLog(id="activity-log", max_lines=100, markup=True)
            yield Input(placeholder="Type / for commands, /help for list", id="command-input")

    def on_mount(self) -> None:
        self._session.add_listener(self._on_session_event)
        self._refresh_timer = self.set_interval(0.25, self._tick)

        # Set robot name on status bar
        status_bar = self.query_one("#status-bar", StatusBar)
        status_bar.robot_name = self._robot_name

        # Welcome message
        if self._session.last_mission is None:
            self._log_activity(
                "Welcome to Defined Robotics! Type /run <task> to start. /help for commands."
            )
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
            _log.debug("Background connect failed", exc_info=True)


    def on_tele_panel_focus_changed(self, event: TelePanel.FocusChanged) -> None:
        """Auto-activate/deactivate teleop when TelePanel gains/loses focus."""
        if event.gained and not self._teleop_mode:
            self._teleop_mode = True
            tele = self.query_one(f"#{TelePanel.PANEL_ID}", TelePanel)
            tele.set_active(True)
            self._log_activity(
                "[yellow]Teleop ON — arrows=move, space=stop, Escape to exit[/yellow]",
                dedup=True,
            )
        elif not event.gained and self._teleop_mode:
            self._teleop_mode = False
            tele = self.query_one(f"#{TelePanel.PANEL_ID}", TelePanel)
            tele.set_active(False)
            self._send_teleop_stop()
            self._log_activity("Teleop OFF.", dedup=True)

    def on_unmount(self) -> None:
        self._session.remove_listener(self._on_session_event)

    # ------------------------------------------------------------------
    # Session event handler (called from any thread)
    # ------------------------------------------------------------------

    def _on_session_event(self, event: SessionEvent) -> None:
        """Handle session events — marshalled to Textual's event loop."""
        self.call_from_thread(self._handle_event, event)

    def _handle_event(self, event: SessionEvent) -> None:
        # Push to all panels
        for panel in self.query(BasePanel):
            panel.on_session_event(event)

        # Also log to activity log — dedup by message content (ignoring timestamp)
        if event.message == self._last_event_msg:
            return
        self._last_event_msg = event.message
        ts = event.timestamp.strftime("%H:%M:%S")
        color = {
            "connection": "blue",
            "executor": "cyan",
            "mission": "green",
            "error": "red",
        }.get(event.category, "white")
        self._log_activity(f"[dim]{ts}[/dim]  [{color}]{event.message}[/{color}]")

    # ------------------------------------------------------------------
    # Periodic tick — update status bar and panels
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

        # Update all panels
        for panel in self.query(BasePanel):
            panel.on_tick(self._session)

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
            self._log_activity(f"[red]{cmd.error}[/red]")
            return

        if cmd.kind == CommandKind.HELP:
            self._log_activity(_HELP_TEXT)
            return

        if cmd.kind == CommandKind.QUIT:
            if self._session.mission_status in (
                MissionStatus.COMPILING, MissionStatus.DEPLOYING, MissionStatus.RUNNING,
            ):
                self._log_activity("[yellow]Mission running. /stop first, then /quit.[/yellow]")
                return
            self.exit()
            return

        if cmd.kind == CommandKind.STATUS:
            conn = self._session.connection_status.value
            mission = self._session.mission_status.value
            pois = len(self._session.list_pois())
            self._log_activity(f"Connection: {conn} | Mission: {mission} | POIs: {pois}")
            return

        if cmd.kind == CommandKind.RUN:
            self._run_task(cmd.args[0], cmd.kwargs)
            return

        if cmd.kind == CommandKind.STOP:
            self._session.stop_mission()
            self._log_activity("Mission stopped.")
            return

        if cmd.kind == CommandKind.RESTART:
            try:
                self._session.restart_mission()
                self._log_activity("Restarting last mission...")
            except RuntimeError as exc:
                self._log_activity(f"[red]{exc}[/red]")
            return

        if cmd.kind == CommandKind.WORLD_ADD:
            name, x_str, y_str = cmd.args
            try:
                x, y = float(x_str), float(y_str)
            except ValueError:
                self._log_activity("[red]Coordinates must be numbers.[/red]")
                return
            self._session.add_poi(name, x, y)
            self._log_activity(f"Added POI '{name}' at ({x}, {y})")
            return

        if cmd.kind == CommandKind.WORLD_LIST:
            pois = self._session.list_pois()
            if not pois:
                self._log_activity("No POIs defined.")
            else:
                lines = [f"  {name}: ({p['center']['x']:.1f}, {p['center']['y']:.1f})" for name, p in pois.items()]
                self._log_activity("POIs:\n" + "\n".join(lines))
            return

        if cmd.kind == CommandKind.WORLD_MARK:
            try:
                x, y = self._session.mark_poi(cmd.args[0])
                self._log_activity(f"Marked '{cmd.args[0]}' at ({x:.2f}, {y:.2f})")
            except Exception as exc:
                self._log_activity(f"[red]Mark failed: {exc}[/red]")
            return

        if cmd.kind == CommandKind.DETAIL:
            diag = self.query_one(f"#{DiagnosticsPanel.PANEL_ID}", DiagnosticsPanel)
            diag.cycle_detail()
            level = {1: "Summary", 2: "Suggestions", 3: "Advanced"}.get(diag._detail_level, "")
            self._log_activity(f"Diagnostics detail: {level}")
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
        tele = self.query_one(f"#{TelePanel.PANEL_ID}", TelePanel)
        tele.set_active(False)
        self._session.emergency_stop()
        self._log_activity("[bold red]⛔ EMERGENCY STOP — robot halted[/bold red]")
        self.query_one("#command-input", Input).focus()

    def _toggle_teleop(self) -> None:
        """Enter or exit teleop mode."""
        self._teleop_mode = not self._teleop_mode
        tele = self.query_one(f"#{TelePanel.PANEL_ID}", TelePanel)
        if self._teleop_mode:
            tele.set_active(True)
            # Blur command input so arrow keys bubble to on_key
            self.set_focus(None)
            self._log_activity(
                "[yellow]Teleop ON — arrows=move, space=stop, Escape or /teleop to exit[/yellow]"
            )
        else:
            tele.set_active(False)
            self._send_teleop_stop()
            self.query_one("#command-input", Input).focus()
            self._log_activity("Teleop OFF.")

    def _send_velocity(self, linear_x: float, angular_z: float, direction: str | None = None) -> None:
        """Publish velocity, update TelePanel display, and schedule auto-stop."""
        self._session.publish_velocity(linear_x, angular_z)
        if self._teleop_mode:
            tele = self.query_one(f"#{TelePanel.PANEL_ID}", TelePanel)
            tele.update_velocity(linear_x, angular_z)
            tele.set_active_direction(direction)
        # Cancel previous auto-stop and schedule a new one
        if self._teleop_stop_handle is not None:
            try:
                self._teleop_stop_handle.stop()
            except Exception:
                _log.debug("Failed to cancel teleop stop timer", exc_info=True)
        self._teleop_stop_handle = self.set_timer(0.6, self._send_teleop_stop)

    def _send_teleop_stop(self) -> None:
        """Publish zero velocity and clear active direction in TelePanel."""
        self._session.publish_velocity(0.0, 0.0)
        if self._teleop_mode:
            tele = self.query_one(f"#{TelePanel.PANEL_ID}", TelePanel)
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
            self._log_activity("[red]No RDF file specified. Use --rdf flag.[/red]")
            return

        # Fuzzy match *.task.yaml
        pattern = str(self._task_dir / "**" / f"*{name}*.task.yaml")
        matches = glob.glob(pattern, recursive=True)
        if not matches:
            self._log_activity(f"[red]No task file matching '{name}' found.[/red]")
            return

        task_path = Path(matches[0])
        if len(matches) > 1:
            names = [Path(m).stem for m in matches[:5]]
            self._log_activity(f"Multiple matches: {names}. Using {task_path.name}")

        try:
            self._session.run_mission(task_path, self._rdf, param_overrides=param_overrides or None)
            suffix = f" ({', '.join(f'{k}={v}' for k, v in param_overrides.items())})" if param_overrides else ""
            self._log_activity(f"Running {task_path.name}{suffix}...")
        except RuntimeError as exc:
            self._log_activity(f"[red]{exc}[/red]")

    def _log_activity(self, text: str, *, dedup: bool = False) -> None:
        """Append a message to the activity log.

        Args:
            text: Rich-markup text to display.
            dedup: If True, skip if identical to the last logged message.
        """
        if dedup and text == self._last_activity_msg:
            return
        self._last_activity_msg = text
        log = self.query_one("#activity-log", RichLog)
        log.write(text)

    # ------------------------------------------------------------------
    # Key bindings
    # ------------------------------------------------------------------

    def action_focus_command(self) -> None:
        if self._teleop_mode:
            self._teleop_mode = False
            tele = self.query_one(f"#{TelePanel.PANEL_ID}", TelePanel)
            tele.set_active(False)
            self._send_teleop_stop()
            self._log_activity("Teleop OFF.")
        self.query_one("#command-input", Input).focus()

    def action_quit_app(self) -> None:
        cmd = parse_command("/quit")
        self._execute_command(cmd)
