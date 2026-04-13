"""Session launcher — manifest loading, world loading, target selection.

Owns the startup sequence: load manifest, load world, select target,
create session. Keeps ``main.py`` as a thin CLI wiring layer.

This module has zero CLI-specific imports (no click, rich, textual).
"""

from __future__ import annotations

import logging
from pathlib import Path

from defined_cli.compiler import compile_task
from defined_cli.manifest import (
    ManifestNotFoundError,
    ManifestValidationError,
    ProjectManifest,
    load_manifest,
)
from defined_cli.mission.session import DefinedSession
from defined_cli.state.blackboard import Blackboard
from defined_cli.state.store import StateStore
from defined_cli.state.world_loader import WorldDefinition, load_world, seed_blackboard
from defined_cli.target import TargetBase
from defined_cli.target.docker_image import DockerImageTarget
from defined_cli.target.sim import SimTarget
from defined_cli.transport.rosbridge import RosbridgeTransport

_log = logging.getLogger(__name__)


def select_target(
    *,
    manifest: ProjectManifest | None = None,
    world_env: str | None = None,
    bt_xml_dir: Path | None = None,
    port: int = 9090,
) -> TargetBase:
    """Select the appropriate target based on manifest.

    When a manifest has a ``sim`` section with an image, use
    DockerImageTarget (pre-built image via ``docker run``).
    Otherwise fall back to SimTarget (docker compose).

    Args:
        manifest: Loaded project manifest (may be None).
        world_env: Gazebo world name for the WORLD_NAME env var.
        bt_xml_dir: Host directory for compiled BT XML (bind-mounted).
        port: Rosbridge port.

    Returns:
        A configured TargetBase instance.
    """
    if manifest is not None and manifest.sim is not None:
        return DockerImageTarget(
            image=manifest.sim.image,
            bt_xml_dir=bt_xml_dir,
            world_env=world_env,
            port=port,
        )
    return SimTarget()


def try_load_manifest(manifest_path: Path | None) -> ProjectManifest | None:
    """Attempt to load a manifest, returning None on failure.

    Errors are logged as warnings — the caller decides whether
    to abort or continue without a manifest.

    Args:
        manifest_path: Explicit path to defined.yaml, or None to skip.

    Returns:
        Loaded manifest, or None if not provided / not found / invalid.
    """
    if manifest_path is None:
        return None

    try:
        return load_manifest(manifest_path)
    except ManifestNotFoundError:
        _log.warning("Manifest not found: %s", manifest_path)
        return None
    except ManifestValidationError as exc:
        _log.warning("Manifest invalid: %s", exc)
        return None


def try_load_world(manifest: ProjectManifest | None) -> WorldDefinition | None:
    """Attempt to load the world file referenced by a manifest.

    Args:
        manifest: Loaded manifest (may be None or lack a world section).

    Returns:
        Loaded world definition, or None.
    """
    if manifest is None or manifest.world is None:
        return None

    if not manifest.world.file.exists():
        _log.warning("World file not found: %s", manifest.world.file)
        return None

    try:
        return load_world(manifest.world.file)
    except Exception as exc:
        _log.warning("Could not load world file %s: %s", manifest.world.file, exc)
        return None


def seed_world_pois(world: WorldDefinition, store: StateStore) -> None:
    """Seed the state store with POIs from a world definition.

    Args:
        world: Loaded world definition.
        store: State store to persist POIs into.
    """
    snapshot = store.load()
    bb = Blackboard(data={"world": {"pois": snapshot.world.pois}})
    seed_blackboard(world, bb)
    snapshot.world.pois = bb.list_pois()
    store.save(snapshot)


def create_session(
    *,
    manifest: ProjectManifest | None = None,
    world: WorldDefinition | None = None,
    host: str = "localhost",
    port: int = 9090,
    bt_xml_dir: Path | None = None,
) -> DefinedSession:
    """Build a fully configured DefinedSession.

    Args:
        manifest: Loaded project manifest.
        world: Loaded world definition.
        host: Rosbridge host.
        port: Rosbridge port.
        bt_xml_dir: Host directory for compiled BT XML.

    Returns:
        A ready-to-connect DefinedSession.
    """
    world_env = world.sim.environment if world and world.sim else None

    target = select_target(
        manifest=manifest,
        world_env=world_env,
        bt_xml_dir=bt_xml_dir,
        port=port,
    )
    transport = RosbridgeTransport(host=host, port=port)
    store = StateStore()

    # Seed POIs from world if available
    if world is not None:
        try:
            seed_world_pois(world, store)
        except Exception as exc:
            _log.warning("Could not seed POIs from world: %s", exc)

    return DefinedSession(
        target=target,
        transport=transport,
        store=store,
        compile_fn=compile_task,
        output_dir=bt_xml_dir,
    )
