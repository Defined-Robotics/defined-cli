"""Tests for the error system."""

from defined_cli.errors import (
    BackendError,
    CompilationError,
    DefinedError,
    TaskExecutionError,
    TransportConnectionError as ConnectionError,
)


class TestDefinedError:

    def test_message_only(self):
        err = DefinedError("Something broke")
        assert err.message == "Something broke"
        assert err.suggestion == ""
        assert err.detail == ""

    def test_with_suggestion(self):
        err = DefinedError("Docker not found", suggestion="Install Docker Desktop")
        assert "Docker not found" in err.format_message()
        assert "Install Docker Desktop" in err.format_message()

    def test_detail_not_in_format_message(self):
        err = DefinedError("Fail", detail="traceback here")
        assert "traceback" not in err.format_message()

    def test_format_message_with_arrow(self):
        err = DefinedError("Bad file", suggestion="Check the path")
        assert "→" in err.format_message()


class TestErrorSubclasses:

    def test_compilation_error_is_defined_error(self):
        err = CompilationError("bad yaml")
        assert isinstance(err, DefinedError)

    def test_connection_error_is_defined_error(self):
        err = ConnectionError("timeout")
        assert isinstance(err, DefinedError)

    def test_backend_error_is_defined_error(self):
        err = BackendError("docker down")
        assert isinstance(err, DefinedError)

    def test_task_execution_error_is_defined_error(self):
        err = TaskExecutionError("nav failed")
        assert isinstance(err, DefinedError)

    def test_all_are_click_exceptions(self):
        """All errors inherit from click.ClickException for automatic CLI handling."""
        import click

        for cls in (CompilationError, ConnectionError, BackendError, TaskExecutionError):
            assert issubclass(cls, click.ClickException)
