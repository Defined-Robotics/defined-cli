"""CLI entry point for the Defined Robotics platform.

Entry points:
- ``defined``           — launch unified TUI (auto-connect sim)
- ``defined --target hw`` — launch TUI, connect hardware
- ``defined compile``   — standalone compiler (no TUI, for CI)
- ``defined world``     — POI management (add, list, mark, watch)

Usage:
    defined --rdf robot.rdf.yaml
    defined compile tasks/patrol.task.yaml --rdf robot.rdf.yaml
    defined world add dock 0.0 0.0
"""

from __future__ import annotations

from pathlib import Path

import click
from rich.console import Console

from . import __version__
from .compiler import compile_task
from .errors import DefinedError
from .state.store import StateStore

_console = Console(stderr=True)


def _show_error(error: DefinedError, *, verbose: bool = False) -> None:
    _console.print(f"\n[bold red]✗ {error.message}[/]")
    if error.suggestion:
        _console.print(f"[yellow]  → {error.suggestion}[/]")
    if verbose and error.detail:
        _console.print(f"\n[dim]{error.detail}[/]")
    _console.print()


# ---------------------------------------------------------------------------
# CLI group — invoke with no subcommand to launch TUI
# ---------------------------------------------------------------------------


@click.group(invoke_without_command=True)
@click.version_option(version=__version__, prog_name="defined")
@click.option("--verbose", is_flag=True, help="Show detailed error output.")
@click.option("--target", type=click.Choice(["sim", "hw"]), default="sim", help="Backend target.")
@click.option("--host", default="localhost", help="Rosbridge host.")
@click.option("--port", default=9090, type=int, help="Rosbridge port.")
@click.option("--rdf", type=click.Path(exists=True, path_type=Path), default=None, help="Robot RDF YAML.")
@click.pass_context
def cli(ctx: click.Context, verbose: bool, target: str, host: str, port: int, rdf: Path | None) -> None:
    """Defined Robotics platform — unified mission control.

    Run with no subcommand to launch the interactive TUI.
    """
    ctx.ensure_object(dict)
    ctx.obj["verbose"] = verbose
    ctx.obj["target"] = target
    ctx.obj["host"] = host
    ctx.obj["port"] = port
    ctx.obj["rdf"] = rdf

    if ctx.invoked_subcommand is None:
        _launch_tui(target=target, host=host, port=port, rdf=rdf)


def _select_target(
    *,
    manifest: object | None = None,
    target_flag: str = "sim",
    world_env: str | None = None,
    port: int = 9090,
) -> object:
    """Select the appropriate target based on manifest and CLI flags.

    When a manifest has a ``sim`` section with an image, use
    DockerImageTarget (pre-built image via ``docker run``).
    Otherwise fall back to SimTarget (docker compose).

    This function is deliberately import-lazy to keep module load fast.
    """
    from .manifest import ProjectManifest
    from .target.docker_image import DockerImageTarget
    from .target.sim import SimTarget

    if manifest is not None and isinstance(manifest, ProjectManifest) and manifest.sim is not None:
        return DockerImageTarget(
            image=manifest.sim.image,
            world_env=world_env,
            port=port,
        )
    return SimTarget()


def _launch_tui(
    *,
    target: str = "sim",
    host: str = "localhost",
    port: int = 9090,
    rdf: Path | None = None,
) -> None:
    """Create a DefinedSession and launch the Textual TUI."""
    from .manifest import ManifestNotFoundError, discover_manifest, load_manifest
    from .mission.session import DefinedSession
    from .state.blackboard import Blackboard
    from .state.world_loader import load_world, seed_blackboard
    from .transport.rosbridge import RosbridgeTransport
    from .tui.defined_app import DefinedApp

    # --- Manifest discovery (fail-soft) ---
    manifest = None
    verbs_dir = None
    try:
        manifest_path = discover_manifest()
        manifest = load_manifest(manifest_path)
        _console.print(f"[dim]Using project: {manifest.project.name} ({manifest_path})[/]")
    except ManifestNotFoundError:
        pass  # No manifest — fall back to CLI flags

    # Manifest values provide defaults; CLI flags override when explicitly set
    if manifest:
        if rdf is None:
            rdf = manifest.robot.rdf
        if manifest.verbs is not None:
            verbs_dir = manifest.verbs.path

    if target == "hw":
        raise click.UsageError(
            "Hardware target is not yet implemented. Use --target sim."
        )

    # --- Target selection ---
    world_env = None
    if manifest and manifest.world is not None and manifest.world.file.exists():
        try:
            world = load_world(manifest.world.file)
            if world.sim is not None:
                world_env = world.sim.environment
        except Exception:
            world = None
    else:
        world = None

    target_obj = _select_target(
        manifest=manifest,
        target_flag=target,
        world_env=world_env,
        port=port,
    )
    transport_obj = RosbridgeTransport(host=host, port=port)
    store = StateStore()

    # --- World loading (seed blackboard with POIs) ---
    if world is not None:
        try:
            snapshot = store.load()
            bb = Blackboard(data={"world": {"pois": snapshot.world.pois}})
            seed_blackboard(world, bb)
            snapshot.world.pois = bb.list_pois()
            store.save(snapshot)
            _console.print(f"[dim]Loaded world: {world.name} ({len(world.pois)} POIs)[/]")
        except Exception as exc:
            _console.print(f"[yellow]Warning: Could not load world file: {exc}[/]")

    session = DefinedSession(
        target=target_obj,
        transport=transport_obj,
        store=store,
        compile_fn=compile_task,
    )

    # Don't block on connect — TUI will appear immediately and
    # show "Disconnected" until the background connect succeeds.
    try:
        app = DefinedApp(session, rdf=rdf)
        app.run()
    except KeyboardInterrupt:
        pass
    finally:
        session.disconnect()


# ---------------------------------------------------------------------------
# compile (standalone, no TUI)
# ---------------------------------------------------------------------------


@cli.command()
@click.argument("task", type=click.Path(exists=True, path_type=Path))
@click.option("--rdf", required=True, type=click.Path(exists=True, path_type=Path), help="Robot RDF YAML.")
@click.option("--output", "-o", type=click.Path(path_type=Path), default=None, help="Output XML path.")
@click.option("--verbs-dir", type=click.Path(exists=True, path_type=Path), default=None, help="Verb templates dir.")
@click.pass_context
def compile(ctx: click.Context, task: Path, rdf: Path, output: Path | None, verbs_dir: Path | None) -> None:
    """Compile a task YAML to BT XML without running it."""
    verbose = ctx.obj.get("verbose", False)
    try:
        output_dir = output.parent if output else None
        result = compile_task(task_yaml=task, rdf_yaml=rdf, verbs_dir=verbs_dir, output_dir=output_dir)
        xml_path = result.xml_path
        if output and output != xml_path:
            xml_path.rename(output)
            xml_path = output
        _console.print(f"[green]✓[/] Compiled to {xml_path}")
        for step in result.steps:
            _console.print(f"  [dim]{step.index + 1}. {step.label}[/]")
    except DefinedError as exc:
        _show_error(exc, verbose=verbose)
        raise SystemExit(1) from exc


# ---------------------------------------------------------------------------
# world (POI management — kept for scripting)
# ---------------------------------------------------------------------------


@cli.group()
def world() -> None:
    """Manage the world model (Points of Interest, map data)."""


@world.command("add")
@click.argument("name")
@click.argument("x", type=float)
@click.argument("y", type=float)
@click.option("--type", "poi_type", type=click.Choice(["static", "constant", "dynamic"]), default="static", show_default=True)
@click.option("--radius", default=0.5, type=float, show_default=True)
def world_add(name: str, x: float, y: float, poi_type: str, radius: float) -> None:
    """Add or update a Point of Interest."""
    from .state.blackboard import Blackboard

    store = StateStore()
    snapshot = store.load()
    bb = Blackboard(data={"world": {"pois": snapshot.world.pois}})
    bb.set_poi(name, (x, y), radius=radius, poi_type=poi_type)
    snapshot.world.pois = bb.list_pois()
    store.save(snapshot)
    _console.print(f"[green]✓[/] POI '{name}' ({x}, {y}) type={poi_type} radius={radius}")


@world.command("list")
def world_list() -> None:
    """List all defined Points of Interest."""
    from rich.table import Table

    store = StateStore()
    snapshot = store.load()
    pois = snapshot.world.pois

    if not pois:
        _console.print("[dim]No POIs defined. Use: defined world add <name> <x> <y>[/]")
        return

    table = Table(title="Points of Interest")
    table.add_column("Name", style="cyan")
    table.add_column("X", justify="right")
    table.add_column("Y", justify="right")
    table.add_column("Type", style="dim")
    table.add_column("Radius", justify="right", style="dim")

    for poi_name, poi in pois.items():
        center = poi.get("center", {})
        table.add_row(
            poi_name,
            str(round(center.get("x", 0.0), 3)),
            str(round(center.get("y", 0.0), 3)),
            poi.get("type", "static"),
            str(poi.get("radius", 0.5)),
        )
    _console.print(table)


@world.command("mark")
@click.argument("name")
@click.option("--type", "poi_type", type=click.Choice(["static", "constant"]), default="static", show_default=True)
@click.option("--radius", default=0.5, type=float, show_default=True)
@click.option("--host", default="localhost")
@click.option("--port", default=9090, type=int)
def world_mark(name: str, poi_type: str, radius: float, host: str, port: int) -> None:
    """Mark the robot's current position as a named POI."""
    from .state.blackboard import Blackboard
    from .transport.pose import fetch_robot_pose

    try:
        x, y = fetch_robot_pose(host=host, port=port)
    except (TimeoutError, ConnectionError) as exc:
        _console.print(f"[bold red]✗ {exc}[/]")
        raise SystemExit(1) from exc

    store = StateStore()
    snapshot = store.load()
    bb = Blackboard(data={"world": {"pois": snapshot.world.pois}})
    bb.set_poi(name, (x, y), radius=radius, poi_type=poi_type)
    snapshot.world.pois = bb.list_pois()
    store.save(snapshot)
    _console.print(f"[green]✓[/] POI '{name}' marked at ({x:.3f}, {y:.3f}) type={poi_type}")


@world.command("watch")
@click.option("--type", "poi_type", type=click.Choice(["static", "constant"]), default="static", show_default=True)
@click.option("--radius", default=0.5, type=float, show_default=True)
@click.option("--host", default="localhost")
@click.option("--port", default=9090, type=int)
def world_watch(poi_type: str, radius: float, host: str, port: int) -> None:
    """Watch for map clicks and save as POIs."""
    from .state.blackboard import Blackboard
    from .transport.pose import subscribe_clicked_point

    store = StateStore()
    count = 0

    def _on_click(x: float, y: float) -> None:
        nonlocal count
        _console.print(f"\n[cyan][click][/] ({x:.2f}, {y:.2f})", end="  ")
        poi_name = click.prompt("Name")
        snapshot = store.load()
        bb = Blackboard(data={"world": {"pois": snapshot.world.pois}})
        bb.set_poi(poi_name, (x, y), radius=radius, poi_type=poi_type)
        snapshot.world.pois = bb.list_pois()
        store.save(snapshot)
        _console.print(f"  [green]✓[/] saved [{poi_type}]")
        count += 1

    try:
        _console.print("[dim]Watching for clicks on /clicked_point… (Ctrl+C to stop)[/]")
        ros, topic = subscribe_clicked_point(host=host, port=port, callback=_on_click)

        import threading
        stop = threading.Event()
        try:
            stop.wait()
        except KeyboardInterrupt:
            pass
    except (ConnectionError, KeyboardInterrupt):
        pass
    finally:
        _console.print(f"\n[dim]Saved {count} POI(s).[/]")
