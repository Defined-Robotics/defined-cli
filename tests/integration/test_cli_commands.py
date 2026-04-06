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

    def test_help_shows_all_commands(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "compile" in result.output
        assert "run" in result.output
        assert "stop" in result.output
        assert "status" in result.output

    def test_version(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["--version"])
        assert result.exit_code == 0
        assert "0.0.1" in result.output


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
        # Click catches the invalid path before our code
        assert result.exit_code != 0

    def test_compile_missing_task(self):
        runner = CliRunner()
        result = runner.invoke(cli, [
            "compile", "/nonexistent/task.yaml",
            "--rdf", RDF_YAML,
        ])
        assert result.exit_code != 0


class TestRunCommand:

    def test_run_help_shows_options(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["run", "--help"])
        assert result.exit_code == 0
        assert "--rdf" in result.output
        assert "--target" in result.output
        assert "--host" in result.output
        assert "--port" in result.output
        assert "--no-launch" in result.output


class TestStopCommand:

    def test_stop_help(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["stop", "--help"])
        assert result.exit_code == 0
        assert "--target" in result.output

    @patch("defined_cli.main._make_target")
    def test_stop_calls_target_stop(self, mock_make_target):
        mock_target = MagicMock()
        mock_make_target.return_value = mock_target
        runner = CliRunner()
        result = runner.invoke(cli, ["stop"])
        assert result.exit_code == 0
        mock_target.stop.assert_called_once()


class TestStatusCommand:

    def test_status_help(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["status", "--help"])
        assert result.exit_code == 0
        assert "--target" in result.output
        assert "--host" in result.output
        assert "--port" in result.output

    @patch("defined_cli.main._make_target")
    def test_status_shows_backend_state(self, mock_make_target):
        mock_target = MagicMock()
        mock_target.status.return_value = TargetStatus.STOPPED
        mock_make_target.return_value = mock_target
        runner = CliRunner()
        result = runner.invoke(cli, ["status"])
        assert result.exit_code == 0
        assert "stopped" in result.output.lower()
