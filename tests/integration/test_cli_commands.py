"""Integration tests for CLI commands via Click's CliRunner."""

from pathlib import Path

from click.testing import CliRunner

from defined_cli.main import cli

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
