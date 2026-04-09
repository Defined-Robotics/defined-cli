"""Base panel class and registry for the Defined Robotics TUI.

All TUI panels subclass ``BasePanel`` and register themselves via the
``@register_panel`` decorator.  The app discovers panels at compose time
by iterating ``PANEL_REGISTRY``.

Custom panels
-------------
To add a custom panel, subclass ``BasePanel``, set ``PANEL_TITLE`` and
``PANEL_ID``, and decorate with ``@register_panel``::

    from defined_cli.tui.panels.base import BasePanel, register_panel

    @register_panel
    class GripperPanel(BasePanel):
        PANEL_TITLE = "GRIPPER"
        PANEL_ID = "panel-gripper"

        def on_tick(self, session):
            grip = session.blackboard.get("robot.gripper", {})
            self.update(f"Position: {grip.get('position', 'unknown')}")
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual.widgets import Static

if TYPE_CHECKING:
    from defined_cli.mission.events import SessionEvent
    from defined_cli.mission.session import DefinedSession


PANEL_REGISTRY: dict[str, type[BasePanel]] = {}
"""Global registry mapping PANEL_ID → panel class."""


def register_panel(cls: type[BasePanel]) -> type[BasePanel]:
    """Class decorator that registers a panel in ``PANEL_REGISTRY``."""
    PANEL_REGISTRY[cls.PANEL_ID] = cls
    return cls


class BasePanel(Static):
    """Base class for all TUI data panels.

    Subclass this and decorate with ``@register_panel`` to create a panel.
    Set ``PANEL_TITLE`` (human-readable border title) and ``PANEL_ID``
    (unique CSS id) as class attributes.

    Override ``on_tick`` to pull data from the session every 0.25 s, and/or
    ``on_session_event`` to react to push events.
    """

    can_focus = True

    PANEL_TITLE: str = "Panel"
    """Human-readable title shown in the panel border."""

    PANEL_ID: str = "panel-base"
    """Unique identifier used as the Textual widget id and CSS selector."""

    def on_mount(self) -> None:
        self.border_title = self.PANEL_TITLE

    def on_session_event(self, event: SessionEvent) -> None:
        """Called when a session event fires.  Override to react."""

    def on_tick(self, session: DefinedSession) -> None:
        """Called every 0.25 s with the live session.  Override to pull data."""
