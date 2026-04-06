"""End-to-end compilation test using real compiler with sample files."""

import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from defined_cli.compiler import CompileResult, compile_task

SAMPLE_DIR = Path(__file__).resolve().parent.parent.parent / "sample"
TASK_YAML = SAMPLE_DIR / "tasks" / "patrol.task.yaml"
RDF_YAML = SAMPLE_DIR / "robot.rdf.yaml"


class TestCompileE2E:

    def test_compile_produces_valid_xml(self, tmp_path):
        result = compile_task(
            task_yaml=TASK_YAML,
            rdf_yaml=RDF_YAML,
            output_dir=tmp_path,
        )
        assert isinstance(result, CompileResult)
        assert result.xml_path.exists()
        assert result.xml_path.suffix == ".xml"

        root = ET.parse(result.xml_path).getroot()
        assert root.get("BTCPP_format") == "4"

    def test_output_has_correct_task_name(self, tmp_path):
        result = compile_task(
            task_yaml=TASK_YAML,
            rdf_yaml=RDF_YAML,
            output_dir=tmp_path,
        )
        assert result.xml_path.name == "PatrolTask.xml"
        assert result.task_name == "PatrolTask"

    def test_output_contains_expected_actions(self, tmp_path):
        result = compile_task(
            task_yaml=TASK_YAML,
            rdf_yaml=RDF_YAML,
            output_dir=tmp_path,
        )
        root = ET.parse(result.xml_path).getroot()
        seq = root.find("BehaviorTree/Sequence")
        assert seq is not None

        action_ids = set()
        for elem in seq.iter():
            if elem.tag == "Action" and elem.get("ID"):
                action_ids.add(elem.get("ID"))
        assert "GoTo" in action_ids
        assert "Report" in action_ids
        assert "Wait" in action_ids

    def test_creates_output_dir_if_missing(self, tmp_path):
        output_dir = tmp_path / "nested" / "build"
        result = compile_task(
            task_yaml=TASK_YAML,
            rdf_yaml=RDF_YAML,
            output_dir=output_dir,
        )
        assert result.xml_path.exists()
        assert output_dir.exists()

    def test_steps_metadata(self, tmp_path):
        result = compile_task(
            task_yaml=TASK_YAML,
            rdf_yaml=RDF_YAML,
            output_dir=tmp_path,
        )
        assert len(result.steps) == 5
        assert result.steps[0].verb == "go_to"
        assert "GoTo" in result.steps[0].label
        assert "(1.0, 0.0)" in result.steps[0].label
        assert result.steps[2].verb == "wait"
        assert "2.0s" in result.steps[2].label
