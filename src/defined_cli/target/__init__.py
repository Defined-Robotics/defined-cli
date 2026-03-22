"""Target protocol — how the CLI manages backend lifecycle.

A target handles starting, stopping, and health-checking the
platform backend. It also translates host filesystem paths to
paths the backend can access (e.g., Docker volume mounts).

The default implementation is ``SimTarget`` which manages the
simulation stack via ``docker compose``.

Key method:
    ``resolve_xml_path(host_path)`` — converts a host-side file
    path to the path the backend sees. For ``SimTarget``, this
    maps ``work/verb-compiler/build/task.xml`` to ``/bt_xml/task.xml``
    (the Docker volume mount point).

Future targets:
    - ``MockTarget`` — hardware mocks (motor encoders, LIDAR)
    - ``HardwareTarget`` — real robot via SSH/serial, with
      ``discover_modules()`` and ``health_check()`` extensions

See Also:
    ``conventions/python.md`` for implementation guidelines.
"""

from __future__ import annotations
