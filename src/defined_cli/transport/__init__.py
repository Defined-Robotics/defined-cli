"""Transport protocol — how the CLI talks to a running backend.

A transport handles pub/sub communication between the CLI (host)
and the platform backend (Docker container, remote hardware, etc.).

The default implementation is ``RosbridgeTransport`` which connects
via WebSocket to rosbridge at ``ws://localhost:9090``.

Contract:
    Implementations must deserialize ``/task_status`` JSON into
    ``platform_interface.TaskResult`` types, not raw dicts. This
    ensures the display layer is transport-agnostic.

Future transports:
    - Zenoh (if ROS2 middleware is swapped per DR-010)
    - gRPC (for direct hardware communication)

See Also:
    ``defined_bringup.platform_interface`` for the boundary types.
"""

from __future__ import annotations
