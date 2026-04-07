"""Mission layer -- resolver and queue.

This package handles mission planning, POI reference resolution,
and mission queuing. It has no CLI-specific dependencies (no click,
rich, or textual) so it can be extracted to a shared library
in the future.
"""

from __future__ import annotations
