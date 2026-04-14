"""Dependency validation — checks verb layer-3 deps against the runtime.

For v0.1.0 this is plumbing only: the fat Docker image has everything,
so ``validate_deps`` always returns an empty list. The infrastructure
is in place for v0.1.1 where ``defined build`` generates a Dockerfile
from the union of verb dependencies.

This module has zero CLI-specific imports (no click, rich, textual).
"""

from __future__ import annotations

import logging
from pathlib import Path

_log = logging.getLogger(__name__)


def validate_deps(*, verbs_dir: Path | None = None) -> list[str]:
    """Union all verb layer-3 deps and check against the runtime.

    Args:
        verbs_dir: Directory containing verb YAML files.

    Returns:
        List of human-readable warning strings for missing deps.
        Empty for v0.1.0 (fat image has everything).
    """
    if verbs_dir is None or not verbs_dir.is_dir():
        return []

    verb_files = list(verbs_dir.glob("*.yaml"))
    if verb_files:
        _log.debug("Found %d verb file(s) in %s", len(verb_files), verbs_dir)

    # v0.1.0: always passes — fat image includes all dependencies.
    # v0.1.1 will parse verb manifests, union deps, and check against
    # the running image's installed package list.
    return []
