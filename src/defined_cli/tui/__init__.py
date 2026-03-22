"""TUI display — full-screen terminal UI for task monitoring.

This is Task #7 from the March 31 milestone. Will use ``textual``
to render live task execution progress:

- Task name and description header
- Step list with status icons (pending/running/done/failed)
- Progress bar with percentage
- Elapsed time

Activated via ``defined run --tui`` (default for interactive
terminals once implemented).
"""

from __future__ import annotations
