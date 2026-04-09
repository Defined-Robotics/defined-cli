"""Tests for TUI panel rendering and command dispatch."""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from defined_cli.mission.events import ConnectionStatus, MissionStatus, SessionEvent
from defined_cli.tui.panels.diagnostics import DiagnosticsPanel
from defined_cli.tui.panels.mission import MissionPanel
from defined_cli.tui.panels.world import WorldPanel


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
        assert "No diagnostics" in text

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
