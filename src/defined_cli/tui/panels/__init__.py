"""TUI panel widgets for the Defined Robotics TUI.

Re-exports the panel base class, registry decorator, and registry dict
so that custom panels can import from ``defined_cli.tui.panels`` directly.
"""

from defined_cli.tui.panels.base import PANEL_REGISTRY, BasePanel, register_panel

__all__ = ["BasePanel", "PANEL_REGISTRY", "register_panel"]
