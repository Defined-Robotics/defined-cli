"""Integration tests for CLI commands via Click's CliRunner."""

from pathlib import Path
from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from defined_cli.main import cli
from defined_cli.target import TargetStatus

SAMPLE_DIR = Path(__file__).resolve().parent.parent.parent / "sample"
TASK_YAML = str(SAMPLE_DIR / "tasks" / "patrol.task.yaml")
RDF_YAML = str(SAMPLE_DIR / "robot.rdf.yaml")


class TestCLIHelp:

    def test_help_shows_available_commands(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "compile" in result.output
        assert "world" in result.output

    def test_help_does_not_show_removed_commands(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["--help"])
        # Extract command names from the Commands section
        commands_section = result.output.split("Commands:")[1] if "Commands:" in result.output else ""
        # Each command line starts with "  <name>  " — extract names
        command_names = [line.split()[0] for line in commands_section.strip().splitlines() if line.strip()]
        assert "run" not in command_names
        assert "stop" not in command_names
        assert "status" not in command_names
        assert "monitor" not in command_names

    def test_version(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["--version"])
        assert result.exit_code == 0
        assert "0.0.1" in result.output

    def test_top_level_has_target_option(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["--help"])
        assert "--target" in result.output
        assert "--host" in result.output
        assert "--rdf" in result.output


class TestCompileCommand:

    def test_compile_success(self, tmp_path):
        runner = CliRunner()
        output = str(tmp_path / "test.xml")
        result = runner.invoke(cli, [
            "compile", TASK_YAML,
            "--rdf", RDF_YAML,
            "-o", output,
        ])
        assert result.exit_code == 0
        assert Path(output).exists()

    def test_compile_missing_rdf(self):
        runner = CliRunner()
        result = runner.invoke(cli, [
            "compile", TASK_YAML,
            "--rdf", "/nonexistent/robot.rdf.yaml",
        ])
        assert result.exit_code != 0

    def test_compile_missing_task(self):
        runner = CliRunner()
        result = runner.invoke(cli, [
            "compile", "/nonexistent/task.yaml",
            "--rdf", RDF_YAML,
        ])
        assert result.exit_code != 0


class TestWorldCommands:

    def test_world_add_exits_zero(self, tmp_path):
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path):
            with patch("defined_cli.main.StateStore") as mock_store_cls:
                from defined_cli.state.store import StateStore
                store = StateStore(path=tmp_path / "state.yaml")
                mock_store_cls.return_value = store
                result = runner.invoke(cli, ["world", "add", "dock", "0.0", "0.0", "--type", "constant"])
        assert result.exit_code == 0
        assert "dock" in result.output

    def test_world_list_exits_zero_when_empty(self, tmp_path):
        runner = CliRunner()
        with patch("defined_cli.main.StateStore") as mock_store_cls:
            from defined_cli.state.store import StateStore
            store = StateStore(path=tmp_path / "state.yaml")
            mock_store_cls.return_value = store
            result = runner.invoke(cli, ["world", "list"])
        assert result.exit_code == 0

    def test_world_list_shows_added_poi(self, tmp_path):
        runner = CliRunner()
        with patch("defined_cli.main.StateStore") as mock_store_cls:
            from defined_cli.state.store import StateStore
            store = StateStore(path=tmp_path / "state.yaml")
            mock_store_cls.return_value = store
            runner.invoke(cli, ["world", "add", "survey-1", "1.5", "2.0"])
            result = runner.invoke(cli, ["world", "list"])
        assert "survey-1" in result.output

    def test_world_help(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["world", "--help"])
        assert result.exit_code == 0
        assert "add" in result.output
        assert "list" in result.output
        assert "mark" in result.output
