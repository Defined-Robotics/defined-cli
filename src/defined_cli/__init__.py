"""Defined Robotics platform orchestrator.

The primary user entry point for compiling, deploying, and monitoring
robot tasks across simulation, hardware mocks, and real hardware.

Architecture:
    The CLI is built around three extensibility protocols:

    - **Target** — how to start/stop a backend (sim, mock, hw)
    - **Transport** — how to talk to a running backend (rosbridge, zenoh)
    - **Display** — how to show progress (rich console, TUI)

    Only ``SimTarget``, ``RosbridgeTransport``, and ``RichDisplay``
    are implemented for the March 31 demo. Adding a new backend is
    a matter of implementing the ``TargetBase`` protocol.

See Also:
    ``conventions/python.md`` for coding standards.
    ``.claude/plans/velvet-crunching-cake.md`` for the full plan.
"""

from __future__ import annotations

__version__ = "0.0.1"
