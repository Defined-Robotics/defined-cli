"""Tests for MonitorDisplay (4-panel TUI)."""

from __future__ import annotations

from collections import deque
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from rich.console import Console

from defined_cli.compiler import StepInfo
from defined_cli.mission.controller import MissionController
from defined_cli.state.model import MissionRecord, RobotStatus
from defined_cli.tui.monitor import MonitorDisplay
from defined_cli.transport import TaskProgress


def _make_controller(
    robot_status: RobotStatus = RobotStatus.IDLE,
    pois: dict | None = None,
    steps: list | None = None,
    history: list | None = None,
    reports: list | None = None,
    step_progress: TaskProgress | None = None,
    current_mission: MissionRecord | None = None,
) -> MagicMock:
    """Build a stub MissionController for display-only tests."""
    ctrl = MagicMock(spec=MissionController)
    ctrl.robot_status = robot_status
    ctrl.pois = pois or {}
    ctrl.steps = steps or []
    ctrl.mission_history = history or []
    ctrl.reports = reports or []
    ctrl.step_progress = step_progress
    ctrl.current_mission = current_mission
    ctrl.is_mission_running = False
    ctrl.last_error = None
    return ctrl


# ---------------------------------------------------------------------------
# Interface
# ---------------------------------------------------------------------------

class TestMonitorDisplayInterface:

    def test_has_run_method(self):
        ctrl = _make_controller()
        display = MonitorDisplay(ctrl)
        assert callable(getattr(display, "run", None))

    def test_has_build_renderable(self):
        ctrl = _make_controller()
        display = MonitorDisplay(ctrl)
        assert callable(getattr(display, "build_renderable", None))


# ---------------------------------------------------------------------------
# Renderable — no crash, correct content
# ---------------------------------------------------------------------------

class TestMonitorDisplayRenderable:

    def _render_to_text(self, display: MonitorDisplay) -> str:
        """Render the display to a plain string for assertion."""
        console = Console(width=120, no_color=True, highlight=False)
        with console.capture() as cap:
            console.print(display.build_renderable())
        return cap.get()

    def test_renders_without_error(self):
        ctrl = _make_controller()
        display = MonitorDisplay(ctrl)
        renderable = display.build_renderable()
        assert renderable is not None

    def test_header_contains_robot_status_idle(self):
        ctrl = _make_controller(robot_status=RobotStatus.IDLE)
        display = MonitorDisplay(ctrl)
        text = self._render_to_text(display)
        assert "IDLE" in text

    def test_header_contains_robot_status_on_mission(self):
        ctrl = _make_controller(robot_status=RobotStatus.ON_MISSION)
        display = MonitorDisplay(ctrl)
        text = self._render_to_text(display)
        assert "ON_MISSION" in text

    def test_poi_panel_shows_poi_names(self):
        pois = {
            "dock": {"center": {"x": 0.0, "y": 0.0}, "radius": 0.3, "type": "constant", "frame": "map"},
            "kitchen": {"center": {"x": 1.5, "y": 2.0}, "radius": 0.5, "type": "static", "frame": "map"},
        }
        ctrl = _make_controller(pois=pois)
        display = MonitorDisplay(ctrl)
        text = self._render_to_text(display)
        assert "dock" in text
        assert "kitchen" in text

    def test_poi_panel_shows_coordinates(self):
        pois = {
            "survey-1": {"center": {"x": 3.0, "y": 1.5}, "radius": 0.5, "type": "static", "frame": "map"},
        }
        ctrl = _make_controller(pois=pois)
        display = MonitorDisplay(ctrl)
        text = self._render_to_text(display)
        assert "3.0" in text
        assert "1.5" in text

    def test_mission_panel_shows_steps(self):
        steps = [
            StepInfo(verb="go_to", label="GoTo (1.0, 0.0)", index=0),
            StepInfo(verb="report", label="Report: arrived", index=1),
        ]
        ctrl = _make_controller(steps=steps)
        display = MonitorDisplay(ctrl)
        text = self._render_to_text(display)
        assert "GoTo" in text or "go_to" in text

    def test_history_panel_shows_records(self):
        history = [
            MissionRecord(
                id="patrol-001",
                task_name="patrol",
                status="SUCCESS",
                started_at="2026-04-07T14:00:00",
                completed_at="2026-04-07T14:01:47",
            )
        ]
        ctrl = _make_controller(history=history)
        display = MonitorDisplay(ctrl)
        text = self._render_to_text(display)
        assert "patrol" in text
        assert "SUCCESS" in text

    def test_reports_panel_shows_messages(self):
        ctrl = _make_controller(reports=["survey-1 visited", "survey-2 visited"])
        display = MonitorDisplay(ctrl)
        text = self._render_to_text(display)
        assert "survey-1 visited" in text

    def test_empty_state_renders_without_crash(self):
        ctrl = _make_controller(robot_status=RobotStatus.OFFLINE)
        display = MonitorDisplay(ctrl)
        text = self._render_to_text(display)
        assert "OFFLINE" in text

    def test_current_mission_shown_when_running(self):
        record = MissionRecord(
            id="patrol-002",
            task_name="patrol",
            status="RUNNING",
            started_at="2026-04-07T15:00:00",
        )
        ctrl = _make_controller(
            robot_status=RobotStatus.ON_MISSION,
            current_mission=record,
        )
        display = MonitorDisplay(ctrl)
        text = self._render_to_text(display)
        assert "patrol" in text
