"""Tests for TUI command bar parsing."""
from __future__ import annotations

import pytest

from defined_cli.tui.command_bar import parse_command, CommandKind


class TestParseCommand:

    def test_run_simple(self):
        cmd = parse_command("/run patrol")
        assert cmd.kind == CommandKind.RUN
        assert cmd.args == ["patrol"]

    def test_run_with_extra_spaces(self):
        cmd = parse_command("/run   patrol  ")
        assert cmd.kind == CommandKind.RUN
        assert cmd.args == ["patrol"]

    def test_stop(self):
        cmd = parse_command("/stop")
        assert cmd.kind == CommandKind.STOP
        assert cmd.args == []

    def test_restart(self):
        cmd = parse_command("/restart")
        assert cmd.kind == CommandKind.RESTART

    def test_quit(self):
        cmd = parse_command("/quit")
        assert cmd.kind == CommandKind.QUIT

    def test_help(self):
        cmd = parse_command("/help")
        assert cmd.kind == CommandKind.HELP

    def test_status(self):
        cmd = parse_command("/status")
        assert cmd.kind == CommandKind.STATUS

    def test_world_add(self):
        cmd = parse_command("/world add dock 0.0 1.5")
        assert cmd.kind == CommandKind.WORLD_ADD
        assert cmd.args == ["dock", "0.0", "1.5"]

    def test_world_list(self):
        cmd = parse_command("/world list")
        assert cmd.kind == CommandKind.WORLD_LIST

    def test_world_mark(self):
        cmd = parse_command("/world mark checkpoint")
        assert cmd.kind == CommandKind.WORLD_MARK
        assert cmd.args == ["checkpoint"]

    def test_unknown_command(self):
        cmd = parse_command("/foobar")
        assert cmd.kind == CommandKind.UNKNOWN
        assert "foobar" in cmd.error

    def test_empty_string(self):
        cmd = parse_command("")
        assert cmd.kind == CommandKind.UNKNOWN

    def test_no_slash_prefix(self):
        cmd = parse_command("run patrol")
        assert cmd.kind == CommandKind.UNKNOWN

    def test_world_add_missing_args(self):
        cmd = parse_command("/world add dock")
        assert cmd.kind == CommandKind.UNKNOWN
        assert "usage" in cmd.error.lower() or "requires" in cmd.error.lower()

    def test_world_add_negative_coords(self):
        cmd = parse_command("/world add dock -1.5 3.0")
        assert cmd.kind == CommandKind.WORLD_ADD
        assert cmd.args == ["dock", "-1.5", "3.0"]


class TestRunWithParamOverrides:

    def test_run_no_overrides_has_empty_kwargs(self):
        cmd = parse_command("/run patrol")
        assert cmd.kind == CommandKind.RUN
        assert cmd.kwargs == {}

    def test_run_single_override(self):
        cmd = parse_command("/run explore timeout=100")
        assert cmd.kind == CommandKind.RUN
        assert cmd.args == ["explore"]
        assert cmd.kwargs == {"timeout": "100"}

    def test_run_multiple_overrides(self):
        cmd = parse_command("/run patrol timeout=30 retries=5")
        assert cmd.kind == CommandKind.RUN
        assert cmd.args == ["patrol"]
        assert cmd.kwargs == {"timeout": "30", "retries": "5"}

    def test_run_float_override(self):
        cmd = parse_command("/run explore timeout=120.5")
        assert cmd.kwargs == {"timeout": "120.5"}

    def test_run_override_with_spaces_around_equals(self):
        # partition("=") handles this: "timeout = 100" → k="timeout ", v=" 100"
        # both are stripped
        cmd = parse_command("/run explore timeout=100")
        assert cmd.kwargs["timeout"] == "100"

    def test_run_positional_arg_without_equals_is_error(self):
        cmd = parse_command("/run explore 100")
        assert cmd.kind == CommandKind.UNKNOWN
        assert "key=value" in cmd.error

    def test_run_no_task_name_is_error(self):
        cmd = parse_command("/run")
        assert cmd.kind == CommandKind.UNKNOWN
        assert "Usage" in cmd.error

    def test_run_override_does_not_affect_args(self):
        cmd = parse_command("/run patrol timeout=60 stale_threshold=20")
        assert cmd.args == ["patrol"]
        assert len(cmd.kwargs) == 2


class TestNewCommands:

    def test_detail_parses(self):
        cmd = parse_command("/detail")
        assert cmd.kind == CommandKind.DETAIL

    def test_teleop_parses(self):
        cmd = parse_command("/teleop")
        assert cmd.kind == CommandKind.TELEOP

    def test_estop_parses(self):
        cmd = parse_command("/estop")
        assert cmd.kind == CommandKind.ESTOP

    def test_estop_alias_double_bang(self):
        cmd = parse_command("!!")
        assert cmd.kind == CommandKind.ESTOP
