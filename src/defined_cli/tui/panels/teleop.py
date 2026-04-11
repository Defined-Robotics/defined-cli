"""TelePanel — always-on manual robot control panel.

Displays a virtual d-pad, live velocity readout, and a prominent E-STOP
reminder.  The panel is passive: it renders state that the parent app
writes via ``update_velocity`` and ``set_active_direction``.  All actual
velocity publishing happens in ``DefinedApp``.

The panel is always visible.  When teleop mode is inactive it shows a
dimmed d-pad with instructions on how to activate.  When active it shows
bright directional highlights and velocity values.

Active direction values: ``"forward"``, ``"backward"``, ``"left"``,
``"right"``, or ``None`` (stopped / no key held).
"""

from __future__ import annotations

from textual.message import Message

from defined_cli.tui.panels.base import BasePanel, register_panel


_DPAD = """\
        [dim]↑[/dim]
   [dim]←[/dim]  ·  [dim]→[/dim]
        [dim]↓[/dim]"""

_DPAD_FORWARD = """\
        [bold cyan]↑[/bold cyan]
   [dim]←[/dim]  ·  [dim]→[/dim]
        [dim]↓[/dim]"""

_DPAD_BACKWARD = """\
        [dim]↑[/dim]
   [dim]←[/dim]  ·  [dim]→[/dim]
        [bold cyan]↓[/bold cyan]"""

_DPAD_LEFT = """\
        [dim]↑[/dim]
   [bold cyan]←[/bold cyan]  ·  [dim]→[/dim]
        [dim]↓[/dim]"""

_DPAD_RIGHT = """\
        [dim]↑[/dim]
   [dim]←[/dim]  ·  [bold cyan]→[/bold cyan]
        [dim]↓[/dim]"""

_DPADS = {
    None: _DPAD,
    "forward": _DPAD_FORWARD,
    "backward": _DPAD_BACKWARD,
    "left": _DPAD_LEFT,
    "right": _DPAD_RIGHT,
}


@register_panel
class TelePanel(BasePanel):
    """Manual control panel — d-pad, velocity readout, and E-STOP reminder.

    Always visible.  Shows inactive state when teleop mode is off,
    active state with live velocity when teleop mode is on.

    State is written by ``DefinedApp`` via the mutator methods; the panel
    itself contains no input logic.
    """

    class FocusChanged(Message):
        """Posted when teleop panel gains or loses focus."""
        def __init__(self, gained: bool) -> None:
            super().__init__()
            self.gained = gained

    PANEL_TITLE = "TELEOP"
    PANEL_ID = "panel-teleop"

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._linear_x: float = 0.0
        self._angular_z: float = 0.0
        self._active_direction: str | None = None
        self._active: bool = False

    def on_focus(self) -> None:
        self.post_message(self.FocusChanged(gained=True))

    def on_blur(self) -> None:
        self.post_message(self.FocusChanged(gained=False))

    # ------------------------------------------------------------------
    # State setters (called by DefinedApp)
    # ------------------------------------------------------------------

    def set_active(self, active: bool) -> None:
        """Toggle between active and inactive teleop display."""
        self._active = active
        if not active:
            self._linear_x = 0.0
            self._angular_z = 0.0
            self._active_direction = None
        self.refresh()

    def update_velocity(self, linear_x: float, angular_z: float) -> None:
        """Update the displayed velocity values and refresh."""
        self._linear_x = linear_x
        self._angular_z = angular_z
        self.refresh()

    def set_active_direction(self, direction: str | None) -> None:
        """Highlight the active direction arrow (or clear highlighting).

        Args:
            direction: One of ``"forward"``, ``"backward"``, ``"left"``,
                ``"right"``, or ``None`` to indicate no movement.
        """
        self._active_direction = direction
        self.refresh()

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    def render(self) -> str:
        if not self._active:
            return (
                f"{_DPAD}\n\n"
                "[dim]Press /teleop to activate\n"
                "arrows=move  space=stop[/dim]\n\n"
                "[bold red]⛔ E-STOP: Ctrl+E or /estop or !![/bold red]"
            )

        dpad = _DPADS.get(self._active_direction, _DPAD)
        lin = f"{self._linear_x:+.2f} m/s"
        ang = f"{self._angular_z:+.2f} rad/s"

        lines = [
            dpad,
            "",
            f"  linear : [cyan]{lin}[/cyan]",
            f"  angular: [cyan]{ang}[/cyan]",
            "",
            "[dim]arrows=move  space=stop[/dim]",
            "[dim]esc or /teleop to exit[/dim]",
            "",
            "[bold red]⛔ E-STOP: Ctrl+E or /estop or !![/bold red]",
        ]
        return "\n".join(lines)
