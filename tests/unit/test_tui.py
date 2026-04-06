"""Tests for LiveDisplay — Rich Live-based task monitor."""

from __future__ import annotations

import time

from defined_cli.compiler import StepInfo
from defined_cli.display import DisplayBase
from defined_cli.transport import TaskProgress


# ---------------------------------------------------------------------------
# Protocol compliance
# ---------------------------------------------------------------------------


class TestLiveDisplayProtocol:
    """LiveDisplay must implement the DisplayBase protocol."""

    def test_implements_display_base(self):
        from defined_cli.tui.app import LiveDisplay

        assert issubclass(LiveDisplay, DisplayBase)

    def test_has_all_required_methods(self):
        from defined_cli.tui.app import LiveDisplay

        for method in ("set_steps", "show_phase", "show_progress", "show_error", "show_success"):
            assert hasattr(LiveDisplay, method), f"Missing method: {method}"

    def test_has_show_log(self):
        from defined_cli.tui.app import LiveDisplay

        assert hasattr(LiveDisplay, "show_log")

    def test_has_show_metadata(self):
        from defined_cli.tui.app import LiveDisplay

        assert hasattr(LiveDisplay, "show_metadata")

    def test_has_build_renderable(self):
        from defined_cli.tui.app import LiveDisplay

        assert hasattr(LiveDisplay, "build_renderable")


# ---------------------------------------------------------------------------
# DisplayBase default methods (backward compatibility)
# ---------------------------------------------------------------------------


class TestDisplayBaseDefaults:
    """New optional methods have default no-op implementations."""

    def test_show_log_exists_on_base(self):
        assert hasattr(DisplayBase, "show_log")

    def test_show_metadata_exists_on_base(self):
        assert hasattr(DisplayBase, "show_metadata")

    def test_rich_display_inherits_show_log(self):
        from defined_cli.display.rich import RichDisplay

        display = RichDisplay()
        # Should not raise — default no-op
        display.show_log("test message")

    def test_rich_display_inherits_show_metadata(self):
        from defined_cli.display.rich import RichDisplay

        display = RichDisplay()
        # Should not raise — default no-op
        display.show_metadata(task_file="test.yaml", target="sim", host="localhost", port=9090)


# ---------------------------------------------------------------------------
# Step state tracking (unchanged core logic)
# ---------------------------------------------------------------------------


class TestStepStateTracking:
    """StepTracker tracks step states from TaskProgress updates."""

    def test_initial_steps_are_pending(self):
        from defined_cli.tui.app import StepState, StepTracker

        steps = [
            StepInfo(verb="go_to", label="GoTo (1.0, 0.0)", index=0),
            StepInfo(verb="report", label="Report", index=1),
            StepInfo(verb="wait", label="Wait (2.0s)", index=2),
        ]
        tracker = StepTracker(steps)
        states = tracker.get_states()
        assert all(s == StepState.PENDING for s in states)

    def test_running_step_updates(self):
        from defined_cli.tui.app import StepState, StepTracker

        steps = [
            StepInfo(verb="go_to", label="GoTo (1.0, 0.0)", index=0),
            StepInfo(verb="report", label="Report", index=1),
            StepInfo(verb="wait", label="Wait (2.0s)", index=2),
        ]
        tracker = StepTracker(steps)
        tracker.update(TaskProgress(step="GoTo", status="RUNNING", current=0, total=3, progress=0))
        states = tracker.get_states()
        assert states[0] == StepState.RUNNING
        assert states[1] == StepState.PENDING
        assert states[2] == StepState.PENDING

    def test_completed_steps_marked_success(self):
        from defined_cli.tui.app import StepState, StepTracker

        steps = [
            StepInfo(verb="go_to", label="GoTo (1.0, 0.0)", index=0),
            StepInfo(verb="report", label="Report", index=1),
            StepInfo(verb="wait", label="Wait (2.0s)", index=2),
        ]
        tracker = StepTracker(steps)
        tracker.update(TaskProgress(step="Report", status="RUNNING", current=1, total=3, progress=33))
        states = tracker.get_states()
        assert states[0] == StepState.SUCCESS
        assert states[1] == StepState.RUNNING
        assert states[2] == StepState.PENDING

    def test_all_success(self):
        from defined_cli.tui.app import StepState, StepTracker

        steps = [
            StepInfo(verb="go_to", label="GoTo", index=0),
            StepInfo(verb="report", label="Report", index=1),
        ]
        tracker = StepTracker(steps)
        tracker.update(TaskProgress(step="Done", status="SUCCESS", current=2, total=2, progress=100))
        states = tracker.get_states()
        assert states[0] == StepState.SUCCESS
        assert states[1] == StepState.SUCCESS

    def test_failure_marks_current_step(self):
        from defined_cli.tui.app import StepState, StepTracker

        steps = [
            StepInfo(verb="go_to", label="GoTo", index=0),
            StepInfo(verb="report", label="Report", index=1),
            StepInfo(verb="wait", label="Wait", index=2),
        ]
        tracker = StepTracker(steps)
        tracker.update(TaskProgress(step="Report", status="FAILURE", current=1, total=3, progress=33))
        states = tracker.get_states()
        assert states[0] == StepState.SUCCESS
        assert states[1] == StepState.FAILED
        assert states[2] == StepState.PENDING


class TestStepStateIcons:
    """Step states render with the correct icons."""

    def test_icons(self):
        from defined_cli.tui.app import StepState

        assert StepState.PENDING.icon == "○"
        assert StepState.RUNNING.icon == "▸"
        assert StepState.SUCCESS.icon == "✓"
        assert StepState.FAILED.icon == "✗"


# ---------------------------------------------------------------------------
# Per-step timing
# ---------------------------------------------------------------------------


class TestStepTiming:
    """StepTracker records per-step elapsed times."""

    def test_no_elapsed_before_start(self):
        from defined_cli.tui.app import StepTracker

        steps = [StepInfo(verb="go_to", label="GoTo", index=0)]
        tracker = StepTracker(steps)
        assert tracker.elapsed_for(0) is None

    def test_elapsed_starts_on_running(self):
        from defined_cli.tui.app import StepTracker

        steps = [StepInfo(verb="go_to", label="GoTo", index=0)]
        tracker = StepTracker(steps)
        tracker.update(TaskProgress(step="GoTo", status="RUNNING", current=0, total=1, progress=0))
        elapsed = tracker.elapsed_for(0)
        assert elapsed is not None
        assert elapsed >= 0.0

    def test_elapsed_stops_on_success(self):
        from defined_cli.tui.app import StepTracker

        steps = [
            StepInfo(verb="go_to", label="GoTo", index=0),
            StepInfo(verb="wait", label="Wait", index=1),
        ]
        tracker = StepTracker(steps)
        tracker.update(TaskProgress(step="GoTo", status="RUNNING", current=0, total=2, progress=0))
        time.sleep(0.05)
        tracker.update(TaskProgress(step="Wait", status="RUNNING", current=1, total=2, progress=50))
        # Step 0 should now have a fixed elapsed (not growing)
        e1 = tracker.elapsed_for(0)
        time.sleep(0.05)
        e2 = tracker.elapsed_for(0)
        assert e1 is not None
        assert e2 is not None
        assert e1 == e2  # frozen after completion


# ---------------------------------------------------------------------------
# Log deque
# ---------------------------------------------------------------------------


class TestLiveDisplayLog:
    """LiveDisplay maintains a bounded log buffer."""

    def test_log_appends(self):
        from defined_cli.tui.app import LiveDisplay

        display = LiveDisplay()
        display.show_log("hello")
        display.show_log("world")
        assert len(display._log_lines) == 2

    def test_log_maxlen(self):
        from defined_cli.tui.app import LiveDisplay

        display = LiveDisplay()
        for i in range(100):
            display.show_log(f"line {i}")
        assert len(display._log_lines) <= 50


# ---------------------------------------------------------------------------
# Renderable output
# ---------------------------------------------------------------------------


class TestBuildRenderable:
    """build_renderable() produces a valid Rich renderable."""

    def test_returns_renderable(self):
        from rich.console import Console

        from defined_cli.tui.app import LiveDisplay

        display = LiveDisplay()
        renderable = display.build_renderable()
        # Should be renderable by Rich without error
        console = Console(file=None, force_terminal=True)
        with console.capture() as capture:
            console.print(renderable)
        output = capture.get()
        assert len(output) > 0

    def test_renderable_with_steps(self):
        from rich.console import Console

        from defined_cli.tui.app import LiveDisplay

        display = LiveDisplay()
        steps = [
            StepInfo(verb="go_to", label="GoTo (1.0, 0.0)", index=0),
            StepInfo(verb="wait", label="Wait (2.0s)", index=1),
        ]
        display.set_steps(steps)
        display.show_phase("Monitoring", "task execution")
        display.show_progress(TaskProgress(step="GoTo", status="RUNNING", current=0, total=2, progress=25))

        renderable = display.build_renderable()
        console = Console(file=None, force_terminal=True)
        with console.capture() as capture:
            console.print(renderable)
        output = capture.get()
        assert "GoTo" in output

    def test_renderable_with_error(self):
        from rich.console import Console

        from defined_cli.errors import TaskExecutionError
        from defined_cli.tui.app import LiveDisplay

        display = LiveDisplay()
        display.show_error(TaskExecutionError("Nav2 failed", suggestion="Check logs"))

        renderable = display.build_renderable()
        console = Console(file=None, force_terminal=True)
        with console.capture() as capture:
            console.print(renderable)
        output = capture.get()
        assert "Nav2 failed" in output

    def test_renderable_with_success(self):
        from rich.console import Console

        from defined_cli.tui.app import LiveDisplay

        display = LiveDisplay()
        display.show_success("Task completed successfully")

        renderable = display.build_renderable()
        console = Console(file=None, force_terminal=True)
        with console.capture() as capture:
            console.print(renderable)
        output = capture.get()
        assert "completed" in output


# ---------------------------------------------------------------------------
# Metadata
# ---------------------------------------------------------------------------


class TestMetadata:
    """LiveDisplay shows task metadata."""

    def test_metadata_stored(self):
        from defined_cli.tui.app import LiveDisplay

        display = LiveDisplay()
        display.show_metadata(task_file="patrol.yaml", target="sim", host="localhost", port=9090)
        assert display._metadata["task_file"] == "patrol.yaml"
        assert display._metadata["target"] == "sim"
