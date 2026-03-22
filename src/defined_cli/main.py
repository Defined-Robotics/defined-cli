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
from .errors import DefinedError

# Rich console for formatted output. Writes to stderr so stdout
# remains clean for piping (e.g., ``defined compile ... | xmllint``).
_console = Console(stderr=True)


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
        xml_path = compile_task(
            task_yaml=task,
            rdf_yaml=rdf,
            verbs_dir=verbs_dir,
            output_dir=output_dir,
        )
        # Rename to exact output path if specified
        if output and output != xml_path:
            xml_path.rename(output)
            xml_path = output

        _console.print(f"[green]✓[/] Compiled to {xml_path}")
    except DefinedError as exc:
        _show_error(exc, verbose=verbose)
        raise SystemExit(1) from exc


# ---------------------------------------------------------------------------
# run (stub — Session 2+3)
# ---------------------------------------------------------------------------


@cli.command()
@click.argument("task", type=click.Path(exists=True, path_type=Path))
@click.option("--rdf", required=True, type=click.Path(exists=True, path_type=Path))
@click.option("--verbs-dir", type=click.Path(exists=True, path_type=Path), default=None)
@click.option("--target", type=click.Choice(["sim"]), default="sim", help="Backend target.")
@click.option("--host", default="localhost", help="Rosbridge host.")
@click.option("--port", default=9090, type=int, help="Rosbridge port.")
@click.option("--no-launch", is_flag=True, help="Skip backend startup (assume already running).")
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
) -> None:
    """Compile and run a task on the robot platform.

    Full pipeline: start backend → connect transport → compile task →
    deploy BT XML → monitor execution via TUI.
    """
    _console.print("[dim]run command not yet implemented (Session 2+3)[/]")
    raise SystemExit(0)


# ---------------------------------------------------------------------------
# stop (stub — Session 2)
# ---------------------------------------------------------------------------


@cli.command()
@click.option("--target", type=click.Choice(["sim"]), default="sim")
def stop(target: str) -> None:
    """Stop the platform backend."""
    _console.print("[dim]stop command not yet implemented (Session 2)[/]")
    raise SystemExit(0)


# ---------------------------------------------------------------------------
# status (stub — Session 2)
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
    _console.print("[dim]status command not yet implemented (Session 2)[/]")
    raise SystemExit(0)
