"""Command bar parser for the Defined TUI.

Parses /commands typed into the command bar and returns structured
ParsedCommand objects. No TUI framework dependency — pure logic.
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
    UNKNOWN = auto()


@dataclass
class ParsedCommand:
    kind: CommandKind
    args: list[str] = field(default_factory=list)
    error: str = ""


def parse_command(raw: str) -> ParsedCommand:
    """Parse a raw command string into a ParsedCommand."""
    raw = raw.strip()
    if not raw or not raw.startswith("/"):
        return ParsedCommand(kind=CommandKind.UNKNOWN, error="Commands must start with /")

    parts = raw.split()
    cmd = parts[0].lower()
    args = parts[1:]

    if cmd == "/run":
        if not args:
            return ParsedCommand(kind=CommandKind.UNKNOWN, error="Usage: /run <task-name>")
        return ParsedCommand(kind=CommandKind.RUN, args=[args[0]])

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

    return ParsedCommand(kind=CommandKind.UNKNOWN, error=f"Unknown command: {cmd}")
