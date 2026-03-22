"""Structured error types with user-facing messages and fix suggestions.

Every error in the CLI carries three fields:

Attributes:
    message: What went wrong (always shown to the user).
    suggestion: How to fix it (shown in yellow after the message).
    detail: Technical detail (shown only with ``--verbose``).

All errors inherit from ``click.ClickException`` so the CLI layer
automatically formats them and exits with code 1.

Example:
    raise CompilationError(
        "Robot 'burger' lacks capability 'robotic_arm'",
        suggestion="Add the capability to your robot.rdf.yaml",
        detail="Required by verb 'pick_up' in step 3",
    )
"""

from __future__ import annotations

import click


class DefinedError(click.ClickException):
    """Base error for the Defined Robotics CLI.

    All CLI errors inherit from this class. Subclass it for each
    error category. The CLI layer catches these and formats them
    with rich (red message, yellow suggestion).

    Attributes:
        message: What went wrong (always shown).
        suggestion: How to fix it (always shown, yellow).
        detail: Technical detail (shown only with ``--verbose``).
    """

    def __init__(
        self,
        message: str,
        suggestion: str = "",
        detail: str = "",
    ) -> None:
        super().__init__(message)
        self.suggestion = suggestion
        self.detail = detail

    def format_message(self) -> str:
        """Format the error for terminal display.

        Returns:
            Multi-line string with message and suggestion.
            Rich markup is applied later by the display layer.
        """
        parts = [self.message]
        if self.suggestion:
            parts.append(f"  → {self.suggestion}")
        return "\n".join(parts)


class CompilationError(DefinedError):
    """Task compilation failed.

    Raised when the compiler pipeline encounters an error. Covers:
    missing files, bad YAML syntax, capability mismatches,
    Jinja2 template errors, and parameter validation failures.
    """


class ConnectionError(DefinedError):
    """Cannot connect to the platform backend.

    Raised when the transport layer fails to establish a connection.
    Covers: rosbridge WebSocket timeout, connection refused,
    unexpected disconnection.
    """


class BackendError(DefinedError):
    """Backend lifecycle error.

    Raised when the target fails to start or stop. Covers: Docker
    not installed, Docker daemon not running, compose file missing,
    image build failure, build directory missing.
    """


class TaskExecutionError(DefinedError):
    """Task execution failed on the robot.

    Raised when the BT executor reports a terminal failure. Covers:
    BT tree returns FAILURE status, Nav2 goal rejected, navigation
    timeout, XML load error.
    """
