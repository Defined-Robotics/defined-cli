"""Tests for the compiler wrapper — error translation for each failure mode."""

from pathlib import Path

import pytest

from defined_cli.compiler import compile_task
from defined_cli.errors import CompilationError


SAMPLE_DIR = Path(__file__).resolve().parent.parent.parent / "sample"
TASK_YAML = SAMPLE_DIR / "tasks" / "patrol.task.yaml"
RDF_YAML = SAMPLE_DIR / "robot.rdf.yaml"


class TestInputValidation:

    def test_missing_task_file(self, tmp_path):
        with pytest.raises(CompilationError, match="Task file not found"):
            compile_task(
                task_yaml=tmp_path / "nonexistent.yaml",
                rdf_yaml=RDF_YAML,
            )

    def test_missing_rdf_file(self, tmp_path):
        with pytest.raises(CompilationError, match="Robot definition not found"):
            compile_task(
                task_yaml=TASK_YAML,
                rdf_yaml=tmp_path / "nonexistent.rdf.yaml",
            )

    def test_missing_verbs_dir(self, tmp_path):
        with pytest.raises(CompilationError, match="Verbs directory not found"):
            compile_task(
                task_yaml=TASK_YAML,
                rdf_yaml=RDF_YAML,
                verbs_dir=tmp_path / "nonexistent_verbs",
            )


class TestBadYAML:

    def test_malformed_task_yaml(self, tmp_path):
        bad_yaml = tmp_path / "bad.yaml"
        bad_yaml.write_text("name: test\nsteps:\n  - verb go_to\n    bad indent")
        with pytest.raises(CompilationError):
            compile_task(task_yaml=bad_yaml, rdf_yaml=RDF_YAML)

    def test_malformed_rdf_yaml(self, tmp_path):
        bad_rdf = tmp_path / "bad.rdf.yaml"
        bad_rdf.write_text(": invalid yaml {{{")
        with pytest.raises(CompilationError):
            compile_task(task_yaml=TASK_YAML, rdf_yaml=bad_rdf)


class TestCapabilityMismatch:

    def test_missing_capability_gives_actionable_error(self, tmp_path):
        """Task requires a capability the robot doesn't have."""
        task_with_arm = tmp_path / "arm_task.yaml"
        task_with_arm.write_text(
            "name: ArmTask\n"
            "steps:\n"
            "  - verb: pick_up\n"
            "    params:\n"
            "      object: cup\n"
        )
        # pick_up verb doesn't exist, so we get a ValueError → CompilationError
        with pytest.raises(CompilationError):
            compile_task(task_yaml=task_with_arm, rdf_yaml=RDF_YAML)


class TestUnknownVerb:

    def test_unknown_verb_error(self, tmp_path):
        task = tmp_path / "bad_verb.yaml"
        task.write_text(
            "name: BadTask\n"
            "steps:\n"
            "  - verb: fly_around\n"
            "    params: {}\n"
        )
        with pytest.raises(CompilationError, match="Unknown verb"):
            compile_task(task_yaml=task, rdf_yaml=RDF_YAML)


class TestMissingFields:

    def test_missing_verb_key(self, tmp_path):
        task = tmp_path / "no_verb.yaml"
        task.write_text(
            "name: NoVerbTask\n"
            "steps:\n"
            "  - params:\n"
            "      x: 1.0\n"
        )
        with pytest.raises(CompilationError, match="Missing required field"):
            compile_task(task_yaml=task, rdf_yaml=RDF_YAML)
