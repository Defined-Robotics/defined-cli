"""CLI entry point for the Defined Robotics platform orchestrator.

This is the primary user-facing interface to the entire platform.
It provides four subcommands:

- ``defined compile`` — compile a task YAML to BT XML
- ``defined run`` — compile, deploy, and monitor a task (Session 2+3)
- ``defined stop`` — stop the platform backend (Session 2)
- ``defined status`` — check platform and task status (Session 2)

Error handling:
    All ``DefinedError`` subclasses are caught and displayed with
    rich formatting (red message, yellow suggestion). The
    ``--verbose`` flag shows technical detail.

Usage:
    defined compile tasks/patrol.task.yaml --rdf robot.rdf.yaml
    defined run tasks/patrol.task.yaml --rdf robot.rdf.yaml
    defined stop
    defined status
"""

from __future__ import annotations

from pathlib import Path

import click
from rich.console import Console

from . import __version__
from .compiler import compile_task
from .display.rich import RichDisplay
from .display import DisplayBase
from .errors import BackendError, DefinedError
from .orchestrator import Orchestrator
from .target import TargetBase, TargetStatus
from .target.sim import SimTarget
from .transport.rosbridge import RosbridgeTransport

# Rich console for formatted output. Writes to stderr so stdout
# remains clean for piping (e.g., ``defined compile ... | xmllint``).
_console = Console(stderr=True)


def _make_target(name: str) -> TargetBase:
    """Map a target name to a concrete implementation."""
    if name == "sim":
        return SimTarget()
    msg = f"Unknown target: {name}"
    raise click.BadParameter(msg)


def _show_error(error: DefinedError, *, verbose: bool = False) -> None:
    """Format and display a ``DefinedError`` with rich markup.

    Args:
        error: The error to display.
        verbose: If ``True``, show the technical detail field.
    """
    _console.print(f"\n[bold red]✗ {error.message}[/]")
    if error.suggestion:
        _console.print(f"[yellow]  → {error.suggestion}[/]")
    if verbose and error.detail:
        _console.print(f"\n[dim]{error.detail}[/]")
    _console.print()


# ---------------------------------------------------------------------------
# CLI group
# ---------------------------------------------------------------------------


@click.group()
@click.version_option(version=__version__, prog_name="defined")
@click.option("--verbose", is_flag=True, help="Show detailed error output.")
@click.pass_context
def cli(ctx: click.Context, verbose: bool) -> None:
    """Defined Robotics platform orchestrator.

    Compile, deploy, and monitor robot tasks across simulation,
    hardware mocks, and real hardware.
    """
    ctx.ensure_object(dict)
    ctx.obj["verbose"] = verbose


# ---------------------------------------------------------------------------
# compile
# ---------------------------------------------------------------------------


@cli.command()
@click.argument("task", type=click.Path(exists=True, path_type=Path))
@click.option(
    "--rdf",
    required=True,
    type=click.Path(exists=True, path_type=Path),
    help="Path to robot RDF YAML file.",
)
@click.option(
    "--output",
    "-o",
    type=click.Path(path_type=Path),
    default=None,
    help="Output XML file path. Default: verb-compiler/build/<task_name>.xml",
)
@click.option(
    "--verbs-dir",
    type=click.Path(exists=True, path_type=Path),
    default=None,
    help="Directory containing verb YAML and Jinja2 template files.",
)
@click.pass_context
def compile(
    ctx: click.Context,
    task: Path,
    rdf: Path,
    output: Path | None,
    verbs_dir: Path | None,
) -> None:
    """Compile a task YAML to BT XML without running it.

    Parses the task, validates robot capabilities against the RDF,
    and emits BehaviorTree.CPP v4 XML.
    """
    verbose = ctx.obj.get("verbose", False)
    try:
        output_dir = output.parent if output else None
        result = compile_task(
            task_yaml=task,
            rdf_yaml=rdf,
            verbs_dir=verbs_dir,
            output_dir=output_dir,
        )
        xml_path = result.xml_path
        # Rename to exact output path if specified
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
# run
# ---------------------------------------------------------------------------


@cli.command()
@click.argument("task", type=click.Path(exists=True, path_type=Path))
@click.option("--rdf", required=True, type=click.Path(exists=True, path_type=Path))
@click.option("--verbs-dir", type=click.Path(exists=True, path_type=Path), default=None)
@click.option("--target", type=click.Choice(["sim"]), default="sim", help="Backend target.")
@click.option("--host", default="localhost", help="Rosbridge host.")
@click.option("--port", default=9090, type=int, help="Rosbridge port.")
@click.option("--no-launch", is_flag=True, help="Skip backend startup (assume already running).")
@click.option("--relaunch", is_flag=True, help="Force teardown and rebuild of the backend before running.")
@click.option("--tui", is_flag=True, help="Use Rich Live TUI display.")
@click.option("--timeout", default=300, type=int, help="Task timeout in seconds.")
@click.pass_context
def run(
    ctx: click.Context,
    task: Path,
    rdf: Path,
    verbs_dir: Path | None,
    target: str,
    host: str,
    port: int,
    no_launch: bool,
    relaunch: bool,
    tui: bool,
    timeout: int,
) -> None:
    """Compile and run a task on the robot platform.

    Full pipeline: start backend → connect transport → compile task →
    deploy BT XML → monitor execution.
    """
    verbose = ctx.obj.get("verbose", False)
    try:
        target_obj = _make_target(target)
        transport_obj = RosbridgeTransport(host=host, port=port)

        if tui:
            display_obj = _make_tui_display()
        else:
            display_obj = RichDisplay()

        orch = Orchestrator(target_obj, transport_obj, display_obj, compile_task)

        if tui:
            _run_with_tui(orch, display_obj, task, rdf, verbs_dir, no_launch, relaunch, timeout, host, port, target)
        else:
            orch.run(task, rdf, verbs_dir=verbs_dir, skip_launch=no_launch, relaunch=relaunch, timeout=timeout)
    except KeyboardInterrupt:
        _console.print("\n[yellow]Interrupted[/]")
        raise SystemExit(130)
    except DefinedError as exc:
        _show_error(exc, verbose=verbose)
        raise SystemExit(1) from exc


def _make_tui_display() -> DisplayBase:
    """Create a LiveDisplay for TUI mode."""
    from .tui.app import LiveDisplay

    return LiveDisplay()


def _run_with_tui(
    orch: Orchestrator,
    display: DisplayBase,
    task: Path,
    rdf: Path,
    verbs_dir: Path | None,
    no_launch: bool,
    relaunch: bool,
    timeout: int,
    host: str,
    port: int,
    target: str,
) -> None:
    """Run the orchestrator with Rich Live display."""
    from .tui.app import LiveDisplay

    live_display: LiveDisplay = display  # type: ignore[assignment]
    live_display.show_metadata(
        task_file=task.name,
        target=target,
        host=host,
        port=port,
    )
    live_display.run(
        lambda: orch.run(task, rdf, verbs_dir=verbs_dir, skip_launch=no_launch, relaunch=relaunch, timeout=timeout)
    )


# ---------------------------------------------------------------------------
# stop
# ---------------------------------------------------------------------------


@cli.command()
@click.option("--target", type=click.Choice(["sim"]), default="sim")
def stop(target: str) -> None:
    """Stop the platform backend."""
    try:
        target_obj = _make_target(target)
        target_obj.stop()
        _console.print("[green]✓ Backend stopped[/]")
    except DefinedError as exc:
        _show_error(exc)
        raise SystemExit(1) from exc


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------


@cli.command()
@click.option("--target", type=click.Choice(["sim"]), default="sim")
@click.option("--host", default="localhost")
@click.option("--port", default=9090, type=int)
def status(target: str, host: str, port: int) -> None:
    """Check platform and task status.

    Reports whether the backend is running, the transport is
    connected, and whether a task is currently executing.
    """
    try:
        target_obj = _make_target(target)
        target_status = target_obj.status()
        _console.print(f"Backend: {target_status.value}")

        if target_status == TargetStatus.RUNNING:
            transport = RosbridgeTransport(host=host, port=port)
            try:
                transport.connect()
                _console.print("Transport: connected")
                transport.disconnect()
            except DefinedError:
                _console.print("[yellow]Transport: not connected[/]")
    except DefinedError as exc:
        _show_error(exc)
        raise SystemExit(1) from exc
