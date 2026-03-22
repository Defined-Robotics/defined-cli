"""Display protocol — how the CLI shows progress to the user.

A display handles rendering pipeline phases, task execution
progress, errors, and completion status.

The default implementation is ``RichDisplay`` which uses the
``rich`` library for formatted console output.

Future displays:
    - ``TUIDisplay`` — full-screen terminal UI using ``textual``
      (Task #7), activated via ``defined run --tui``

See Also:
    ``defined_cli.errors`` for the error types that displays render.
"""

from __future__ import annotations
