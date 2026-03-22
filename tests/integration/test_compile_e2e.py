"""End-to-end compilation test using real compiler with sample files."""

import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from defined_cli.compiler import compile_task

SAMPLE_DIR = Path(__file__).resolve().parent.parent.parent / "sample"
TASK_YAML = SAMPLE_DIR / "tasks" / "patrol.task.yaml"
RDF_YAML = SAMPLE_DIR / "robot.rdf.yaml"


class TestCompileE2E:

    def test_compile_produces_valid_xml(self, tmp_path):
        xml_path = compile_task(
            task_yaml=TASK_YAML,
            rdf_yaml=RDF_YAML,
            output_dir=tmp_path,
        )
        assert xml_path.exists()
        assert xml_path.suffix == ".xml"

        # Parse and validate structure
        root = ET.parse(xml_path).getroot()
        assert root.get("BTCPP_format") == "4"

    def test_output_has_correct_task_name(self, tmp_path):
        xml_path = compile_task(
            task_yaml=TASK_YAML,
            rdf_yaml=RDF_YAML,
            output_dir=tmp_path,
        )
        assert xml_path.name == "PatrolTask.xml"

    def test_output_contains_expected_actions(self, tmp_path):
        xml_path = compile_task(
            task_yaml=TASK_YAML,
            rdf_yaml=RDF_YAML,
            output_dir=tmp_path,
        )
        root = ET.parse(xml_path).getroot()
        seq = root.find("BehaviorTree/Sequence")
        assert seq is not None

        # Should have GoTo, Report, Wait actions
        action_ids = set()
        for elem in seq.iter():
            if elem.tag == "Action" and elem.get("ID"):
                action_ids.add(elem.get("ID"))
        assert "GoTo" in action_ids
        assert "Report" in action_ids
        assert "Wait" in action_ids

    def test_creates_output_dir_if_missing(self, tmp_path):
        output_dir = tmp_path / "nested" / "build"
        xml_path = compile_task(
            task_yaml=TASK_YAML,
            rdf_yaml=RDF_YAML,
            output_dir=output_dir,
        )
        assert xml_path.exists()
        assert output_dir.exists()
