"""Tests for TUI panel rendering and command dispatch."""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from defined_cli.mission.events import ConnectionStatus, MissionStatus, SessionEvent
from defined_cli.tui.panels.base import PANEL_REGISTRY, BasePanel, register_panel
from defined_cli.tui.panels.diagnostics import DiagnosticsPanel
from defined_cli.tui.panels.mission import MissionPanel
from defined_cli.tui.panels.status_bar import StatusBar
from defined_cli.tui.panels.teleop import TelePanel
from defined_cli.tui.panels.world import WorldPanel


class TestBasePanel:
    """BasePanel base class and registry."""

    def test_can_focus_is_true(self):
        assert BasePanel.can_focus is True

    def test_panel_registry_contains_builtin_panels(self):
        assert "panel-mission" in PANEL_REGISTRY
        assert "panel-world" in PANEL_REGISTRY
        assert "panel-diagnostics" in PANEL_REGISTRY
        assert "panel-teleop" in PANEL_REGISTRY

    def test_panel_registry_maps_to_correct_classes(self):
        assert PANEL_REGISTRY["panel-mission"] is MissionPanel
        assert PANEL_REGISTRY["panel-world"] is WorldPanel
        assert PANEL_REGISTRY["panel-diagnostics"] is DiagnosticsPanel
        assert PANEL_REGISTRY["panel-teleop"] is TelePanel

    def test_register_panel_decorator(self):
        @register_panel
        class _TestPanel(BasePanel):
            PANEL_TITLE = "TEST"
            PANEL_ID = "panel-test-unique"

        assert PANEL_REGISTRY["panel-test-unique"] is _TestPanel
        # Cleanup
        del PANEL_REGISTRY["panel-test-unique"]

    def test_builtin_panels_subclass_base(self):
        assert issubclass(MissionPanel, BasePanel)
        assert issubclass(WorldPanel, BasePanel)
        assert issubclass(DiagnosticsPanel, BasePanel)
        assert issubclass(TelePanel, BasePanel)

    def test_builtin_panels_have_titles(self):
        assert MissionPanel.PANEL_TITLE == "MISSION"
        assert WorldPanel.PANEL_TITLE == "WORLD"
        assert DiagnosticsPanel.PANEL_TITLE == "DIAGNOSTICS"
        assert TelePanel.PANEL_TITLE == "TELEOP"


class TestStatusBar:
    """StatusBar rendering."""

    def test_default_render(self):
        bar = StatusBar()
        text = bar.render()
        assert "unknown" in text
        assert "Disconnected" in text

    def test_robot_name_shown(self):
        bar = StatusBar()
        bar.robot_name = "turtlebot3-burger"
        text = bar.render()
        assert "turtlebot3-burger" in text

    def test_connected_shows_green(self):
        bar = StatusBar()
        bar.connection = "Connected"
        text = bar.render()
        assert "[green]" in text

    def test_disconnected_shows_red(self):
        bar = StatusBar()
        bar.connection = "Disconnected"
        text = bar.render()
        assert "[red]" in text

    def test_connecting_shows_yellow(self):
        bar = StatusBar()
        bar.connection = "Connecting"
        text = bar.render()
        assert "[yellow]" in text

    def test_reconnecting_shows_yellow(self):
        bar = StatusBar()
        bar.connection = "Reconnecting"
        text = bar.render()
        assert "[yellow]" in text


class TestTelePanelActiveInactive:
    """TelePanel active/inactive mode rendering."""

    def test_inactive_shows_activate_hint(self):
        panel = TelePanel()
        text = panel.render()
        assert "/teleop to activate" in text

    def test_inactive_does_not_show_velocity(self):
        panel = TelePanel()
        text = panel.render()
        assert "linear" not in text

    def test_active_shows_velocity(self):
        panel = TelePanel()
        panel.set_active(True)
        text = panel.render()
        assert "linear" in text
        assert "angular" in text

    def test_set_active_false_resets_velocity(self):
        panel = TelePanel()
        panel.set_active(True)
        panel.update_velocity(0.2, 0.5)
        panel.set_active(False)
        assert panel._linear_x == 0.0
        assert panel._angular_z == 0.0
        assert panel._active_direction is None


class TestTelePanelFocusChanged:
    """TelePanel posts FocusChanged message on focus/blur."""

    def test_focus_changed_message_gained(self):
        msg = TelePanel.FocusChanged(gained=True)
        assert msg.gained is True

    def test_focus_changed_message_lost(self):
        msg = TelePanel.FocusChanged(gained=False)
        assert msg.gained is False


class TestDiagnosticsPanelTimestamps:
    """DiagnosticsPanel shows timestamps."""

    def test_event_has_timestamp_in_render(self):
        panel = DiagnosticsPanel()
        event = SessionEvent(
            timestamp=datetime(2026, 4, 9, 14, 32, 5, tzinfo=timezone.utc),
            category="mission",
            message="Mission started",
            suggestion=None,
            detail=None,
        )
        panel.add_event(event)
        text = panel.render()
        assert "14:32:05" in text
        assert "Mission started" in text


class TestMissionPanel:

    def test_empty_render(self):
        panel = MissionPanel()
        text = panel.render()
        assert "No active mission" in text

    def test_update_steps(self):
        panel = MissionPanel()
        steps = [
            ("✓", "GoTo dock", "SUCCESS"),
            ("⟳", "Report checkpoint", "RUNNING"),
            ("○", "GoTo survey-1", "PENDING"),
        ]
        panel.update_steps(steps, 40, "patrol")
        text = panel.render()
        assert "patrol" in text
        assert "GoTo dock" in text
        assert "Report checkpoint" in text
        assert "40%" in text

    def test_clear_mission(self):
        panel = MissionPanel()
        panel.update_steps([("✓", "Step1", "SUCCESS")], 100, "test")
        panel.clear_mission()
        text = panel.render()
        assert "No active mission" in text


class TestWorldPanel:

    def test_empty_render(self):
        panel = WorldPanel()
        text = panel.render()
        assert "No POIs" in text

    def test_with_pois(self):
        panel = WorldPanel()
        panel.update_pois({
            "dock": {"center": {"x": 0.0, "y": 0.0}, "type": "constant"},
            "survey": {"center": {"x": 1.5, "y": 2.5}, "type": "static"},
        })
        text = panel.render()
        assert "dock" in text
        assert "survey" in text
        assert "1.5" in text


class TestDiagnosticsPanel:

    def _make_event(self, category="mission", message="test", suggestion=None, detail=None):
        return SessionEvent(
            timestamp=datetime.now(timezone.utc),
            category=category,
            message=message,
            suggestion=suggestion,
            detail=detail,
        )

    def test_empty_render(self):
        panel = DiagnosticsPanel()
        text = panel.render()
        assert "Waiting for events" in text

    def test_add_event_shows_message(self):
        panel = DiagnosticsPanel()
        panel.add_event(self._make_event(message="Step 1 completed"))
        text = panel.render()
        assert "Step 1 completed" in text

    def test_detail_level_1_hides_suggestion(self):
        panel = DiagnosticsPanel()
        panel.add_event(self._make_event(
            message="Failed",
            suggestion="Check robot position",
        ))
        panel.set_detail_level(1)
        text = panel.render()
        assert "Failed" in text
        assert "Check robot position" not in text

    def test_detail_level_2_shows_suggestion(self):
        panel = DiagnosticsPanel()
        panel.add_event(self._make_event(
            message="Failed",
            suggestion="Check robot position",
        ))
        panel.set_detail_level(2)
        text = panel.render()
        assert "Check robot position" in text

    def test_detail_level_3_shows_detail(self):
        panel = DiagnosticsPanel()
        panel.add_event(self._make_event(
            message="Error",
            detail={"step": 3, "verb": "GoTo"},
        ))
        panel.set_detail_level(3)
        text = panel.render()
        assert "step" in text
        assert "GoTo" in text

    def test_cycle_detail(self):
        panel = DiagnosticsPanel()
        assert panel._detail_level == 1
        panel.cycle_detail()
        assert panel._detail_level == 2
        panel.cycle_detail()
        assert panel._detail_level == 3
        panel.cycle_detail()
        assert panel._detail_level == 1

    def test_multiple_events(self):
        panel = DiagnosticsPanel()
        for i in range(5):
            panel.add_event(self._make_event(message=f"Event {i}"))
        text = panel.render()
        assert "Event 4" in text
        assert "Event 0" in text

    def test_hint_text_uses_detail_command(self):
        panel = DiagnosticsPanel()
        panel.add_event(self._make_event(message="anything"))
        text = panel.render()
        assert "/detail" in text
        assert "d/D" not in text


class TestMissionPanelProgress:
    """Progress display variants for the mission panel."""

    def test_running_step_at_zero_percent_shows_spinner(self):
        panel = MissionPanel()
        panel.update_steps([("⟳", "Explore", "RUNNING")], 0, "explore")
        text = panel.render()
        assert "⟳ Running..." in text
        assert "%" not in text

    def test_progress_bar_shown_when_progress_positive(self):
        panel = MissionPanel()
        panel.update_steps([("✓", "GoTo", "SUCCESS"), ("⟳", "Report", "RUNNING")], 50, "patrol")
        text = panel.render()
        assert "50%" in text
        assert "⟳ Running..." not in text

    def test_pending_steps_at_zero_percent_shows_no_bar_and_no_spinner(self):
        panel = MissionPanel()
        panel.update_steps([("○", "GoTo", "PENDING"), ("○", "Report", "PENDING")], 0, "patrol")
        text = panel.render()
        assert "⟳ Running..." not in text
        assert "%" not in text

    def test_fully_complete_shows_100_percent_bar(self):
        panel = MissionPanel()
        panel.update_steps([("✓", "GoTo", "SUCCESS"), ("✓", "Report", "SUCCESS")], 100, "patrol")
        text = panel.render()
        assert "100%" in text
        assert "⟳ Running..." not in text


class TestTelePanel:
    """TelePanel — manual control panel with E-STOP."""

    def test_idle_render_shows_inactive_dpad(self):
        panel = TelePanel()
        text = panel.render()
        # TELEOP title is now in the border, not in render output
        assert "/teleop to activate" in text
        assert "ESTOP" in text.upper() or "E-STOP" in text or "⛔" in text

    def test_velocity_display_shows_zero_when_active(self):
        panel = TelePanel()
        panel.set_active(True)
        text = panel.render()
        # Should show current velocity readout defaulting to 0
        assert "0.0" in text or "0.00" in text

    def test_update_velocity_reflects_in_render(self):
        panel = TelePanel()
        panel.set_active(True)
        panel.update_velocity(0.2, 0.5)
        text = panel.render()
        assert "0.2" in text or "0.20" in text

    def test_active_direction_shown_in_render(self):
        panel = TelePanel()
        panel.set_active(True)
        panel.set_active_direction("forward")
        text = panel.render()
        # Forward direction should be highlighted somehow
        assert "forward" in text.lower() or "↑" in text

    def test_no_active_direction_by_default(self):
        panel = TelePanel()
        # Should not show any active direction
        text = panel.render()
        assert panel._active_direction is None

    def test_stop_clears_active_direction(self):
        panel = TelePanel()
        panel.set_active_direction("forward")
        panel.set_active_direction(None)
        assert panel._active_direction is None
