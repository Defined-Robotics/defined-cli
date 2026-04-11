"""Command bar parser for the Defined TUI.

Parses /commands typed into the command bar and returns structured
``ParsedCommand`` objects.  No TUI framework dependency — pure logic.

Commands are defined declaratively in ``_COMMANDS``. To add a new
command, add an entry to the dict — no parsing logic changes needed.

Available commands
------------------
/run <task> [key=value ...]
    Compile and run a task file (fuzzy-matched against ``*.task.yaml`` in the
    current directory tree).  Optional ``key=value`` pairs override matching
    step parameters at compile time.

/stop               Stop the current mission gracefully.
/restart            Re-run the most recently executed mission with the same args.
/teleop             Toggle manual-control mode (arrow keys + space in the TUI).
/estop  or  !!      Emergency stop — publish zero velocity and abort the mission
                    immediately.  ``!!`` is a two-keystroke alias so it can be
                    entered faster in urgent situations.
/detail             Cycle the diagnostics panel through three detail levels:
                    Summary → Suggestions → Advanced.
/world add <n> <x> <y>  Add or update a named POI.
/world list         List all POIs.
/world mark <name>  Record the robot's current pose as a named POI.
/status             Print connection, mission, and world status.
/help               Print the in-app help text.
/quit               Exit the TUI (blocked while a mission is running).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto


# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------


class CommandKind(Enum):
    RUN = auto()
    STOP = auto()
    RESTART = auto()
    QUIT = auto()
    HELP = auto()
    STATUS = auto()
    WORLD_ADD = auto()
    WORLD_LIST = auto()
    WORLD_MARK = auto()
    DETAIL = auto()
    TELEOP = auto()
    ESTOP = auto()
    UNKNOWN = auto()


@dataclass
class ParsedCommand:
    kind: CommandKind
    args: list[str] = field(default_factory=list)
    kwargs: dict[str, str] = field(default_factory=dict)
    error: str = ""


# ---------------------------------------------------------------------------
# Declarative command registry
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _CommandSpec:
    """Spec for a single command or subcommand.

    Args:
        kind: The ``CommandKind`` this command maps to.
        n_args: Number of required positional arguments.
        usage: Error message shown when argument count is wrong.
        has_kwargs: If True, extra arguments after positional args are
            parsed as ``key=value`` pairs.
    """

    kind: CommandKind
    n_args: int = 0
    usage: str = ""
    has_kwargs: bool = False


_COMMANDS: dict[str, _CommandSpec | dict[str, _CommandSpec]] = {
    "/run": _CommandSpec(
        CommandKind.RUN,
        n_args=1,
        usage="Usage: /run <task-name> [key=value ...]",
        has_kwargs=True,
    ),
    "/stop": _CommandSpec(CommandKind.STOP),
    "/restart": _CommandSpec(CommandKind.RESTART),
    "/quit": _CommandSpec(CommandKind.QUIT),
    "/help": _CommandSpec(CommandKind.HELP),
    "/status": _CommandSpec(CommandKind.STATUS),
    "/detail": _CommandSpec(CommandKind.DETAIL),
    "/teleop": _CommandSpec(CommandKind.TELEOP),
    "/estop": _CommandSpec(CommandKind.ESTOP),
    "/world": {
        "add": _CommandSpec(
            CommandKind.WORLD_ADD,
            n_args=3,
            usage="Usage: /world add <name> <x> <y>. Requires name and coordinates.",
        ),
        "list": _CommandSpec(CommandKind.WORLD_LIST),
        "mark": _CommandSpec(
            CommandKind.WORLD_MARK,
            n_args=1,
            usage="Usage: /world mark <name>. Requires a name.",
        ),
    },
}


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


def parse_command(raw: str) -> ParsedCommand:
    """Parse a raw command string into a ParsedCommand.

    Standard commands begin with ``/``.  Emergency stop also accepts the
    shorthand ``!!`` so it can be triggered with two quick keystrokes.
    """
    raw = raw.strip()
    if not raw:
        return ParsedCommand(kind=CommandKind.UNKNOWN, error="Commands must start with /")

    # Emergency-stop shorthand: !! (no slash needed — speed matters)
    if raw == "!!":
        return ParsedCommand(kind=CommandKind.ESTOP)

    if not raw.startswith("/"):
        return ParsedCommand(kind=CommandKind.UNKNOWN, error="Commands must start with /")

    parts = raw.split()
    cmd = parts[0].lower()
    args = parts[1:]

    entry = _COMMANDS.get(cmd)
    if entry is None:
        return ParsedCommand(kind=CommandKind.UNKNOWN, error=f"Unknown command: {cmd}")

    # Subcommand group (e.g. /world add|list|mark)
    if isinstance(entry, dict):
        if not args:
            subs = ", ".join(entry)
            return ParsedCommand(
                kind=CommandKind.UNKNOWN,
                error=f"Usage: {cmd} <{'|'.join(entry)}> ...",
            )
        subcmd = args[0].lower()
        spec = entry.get(subcmd)
        if spec is None:
            return ParsedCommand(
                kind=CommandKind.UNKNOWN,
                error=f"Unknown {cmd[1:]} subcommand: {subcmd}",
            )
        args = args[1:]
    else:
        spec = entry

    # Validate required positional args
    if len(args) < spec.n_args:
        return ParsedCommand(kind=CommandKind.UNKNOWN, error=spec.usage)

    positional = args[: spec.n_args]
    extras = args[spec.n_args :]

    # Parse key=value kwargs if the command supports them
    kwargs: dict[str, str] = {}
    if spec.has_kwargs:
        for extra in extras:
            if "=" not in extra:
                return ParsedCommand(
                    kind=CommandKind.UNKNOWN,
                    error=f"Invalid argument '{extra}'. Use key=value format, e.g. timeout=100",
                )
            k, _, v = extra.partition("=")
            kwargs[k.strip()] = v.strip()

    return ParsedCommand(kind=spec.kind, args=positional, kwargs=kwargs)
