"""Tests for RichDisplay — the Rich-based console renderer."""

from io import StringIO

from rich.console import Console

from defined_cli.compiler import StepInfo
from defined_cli.display.rich import RichDisplay
from defined_cli.errors import CompilationError
from defined_cli.transport import TaskProgress


def _make_display() -> tuple[RichDisplay, StringIO]:
    """Create a RichDisplay that captures output to a StringIO buffer."""
    buf = StringIO()
    console = Console(file=buf, no_color=True, width=120)
    return RichDisplay(console=console), buf


class TestSetSteps:
    def test_prints_step_labels(self):
        display, buf = _make_display()
        steps = [
            StepInfo(verb="go_to", label="GoTo (1.0, 0.0)", index=0),
            StepInfo(verb="report", label="Report", index=1),
        ]
        display.set_steps(steps)
        output = buf.getvalue()
        assert "GoTo (1.0, 0.0)" in output
        assert "Report" in output


class TestShowPhase:
    def test_contains_phase_name(self):
        display, buf = _make_display()
        display.show_phase("Compiling", "patrol.task.yaml")
        output = buf.getvalue()
        assert "Compiling" in output
        assert "patrol.task.yaml" in output

    def test_multiple_phases(self):
        display, buf = _make_display()
        display.show_phase("Starting", "simulation backend")
        display.show_phase("Connecting", "rosbridge")
        output = buf.getvalue()
        assert "Starting" in output
        assert "Connecting" in output


class TestShowProgress:
    def test_contains_percentage(self):
        display, buf = _make_display()
        progress = TaskProgress(step="GoTo", status="RUNNING", current=2, total=5, progress=40)
        display.show_progress(progress)
        output = buf.getvalue()
        assert "40%" in output
        assert "GoTo" in output

    def test_contains_step_counts(self):
        display, buf = _make_display()
        progress = TaskProgress(step="Wait", status="RUNNING", current=3, total=5, progress=60)
        display.show_progress(progress)
        output = buf.getvalue()
        assert "3" in output
        assert "5" in output

    def test_success_status(self):
        display, buf = _make_display()
        progress = TaskProgress(step="Done", status="SUCCESS", current=5, total=5, progress=100)
        display.show_progress(progress)
        output = buf.getvalue()
        assert "Done" in output
        assert "100%" in output

    def test_failure_status(self):
        display, buf = _make_display()
        progress = TaskProgress(step="GoTo", status="FAILURE", current=2, total=5, progress=40)
        display.show_progress(progress)
        output = buf.getvalue()
        assert "GoTo" in output
        assert "FAILURE" in output or "40%" in output


class TestShowError:
    def test_contains_message_and_suggestion(self):
        display, buf = _make_display()
        error = CompilationError(
            "Robot lacks capability 'arm'",
            suggestion="Add the capability to your RDF",
        )
        display.show_error(error)
        output = buf.getvalue()
        assert "Robot lacks capability 'arm'" in output
        assert "Add the capability to your RDF" in output

    def test_error_without_suggestion(self):
        display, buf = _make_display()
        error = CompilationError("Something broke")
        display.show_error(error)
        output = buf.getvalue()
        assert "Something broke" in output


class TestShowSuccess:
    def test_contains_message(self):
        display, buf = _make_display()
        display.show_success("Task completed successfully")
        output = buf.getvalue()
        assert "Task completed successfully" in output
