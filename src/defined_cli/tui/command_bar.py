"""Command bar parser for the Defined TUI.

Parses /commands typed into the command bar and returns structured
``ParsedCommand`` objects.  No TUI framework dependency — pure logic.

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

    if cmd == "/run":
        if not args:
            return ParsedCommand(
                kind=CommandKind.UNKNOWN,
                error="Usage: /run <task-name> [key=value ...]",
            )
        task_name = args[0]
        kwargs: dict[str, str] = {}
        for extra in args[1:]:
            if "=" not in extra:
                return ParsedCommand(
                    kind=CommandKind.UNKNOWN,
                    error=f"Invalid argument '{extra}'. Use key=value format, e.g. timeout=100",
                )
            k, _, v = extra.partition("=")
            kwargs[k.strip()] = v.strip()
        return ParsedCommand(kind=CommandKind.RUN, args=[task_name], kwargs=kwargs)

    if cmd == "/stop":
        return ParsedCommand(kind=CommandKind.STOP)

    if cmd == "/restart":
        return ParsedCommand(kind=CommandKind.RESTART)

    if cmd == "/quit":
        return ParsedCommand(kind=CommandKind.QUIT)

    if cmd == "/help":
        return ParsedCommand(kind=CommandKind.HELP)

    if cmd == "/status":
        return ParsedCommand(kind=CommandKind.STATUS)

    if cmd == "/world":
        if not args:
            return ParsedCommand(kind=CommandKind.UNKNOWN, error="Usage: /world <add|list|mark> ...")
        subcmd = args[0].lower()
        sub_args = args[1:]

        if subcmd == "add":
            if len(sub_args) < 3:
                return ParsedCommand(
                    kind=CommandKind.UNKNOWN,
                    error="Usage: /world add <name> <x> <y>. Requires name and coordinates.",
                )
            return ParsedCommand(kind=CommandKind.WORLD_ADD, args=sub_args[:3])

        if subcmd == "list":
            return ParsedCommand(kind=CommandKind.WORLD_LIST)

        if subcmd == "mark":
            if not sub_args:
                return ParsedCommand(
                    kind=CommandKind.UNKNOWN,
                    error="Usage: /world mark <name>. Requires a name.",
                )
            return ParsedCommand(kind=CommandKind.WORLD_MARK, args=[sub_args[0]])

        return ParsedCommand(
            kind=CommandKind.UNKNOWN,
            error=f"Unknown world subcommand: {subcmd}",
        )

    if cmd == "/detail":
        return ParsedCommand(kind=CommandKind.DETAIL)

    if cmd == "/teleop":
        return ParsedCommand(kind=CommandKind.TELEOP)

    if cmd == "/estop":
        return ParsedCommand(kind=CommandKind.ESTOP)

    return ParsedCommand(kind=CommandKind.UNKNOWN, error=f"Unknown command: {cmd}")
