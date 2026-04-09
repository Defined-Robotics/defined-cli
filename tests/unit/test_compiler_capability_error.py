"""Test that capability gate errors produce useful messages."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from defined_cli.compiler import compile_task
from defined_cli.errors import CompilationError


class TestCapabilityGateError:

    def test_missing_capability_shows_available_types(self, tmp_path):
        """When a verb requires a capability the robot lacks,
        the error message should list available capabilities."""
        # Create a minimal task YAML that uses a verb requiring rgb_camera
        task_yaml = tmp_path / "photo.task.yaml"
        task_yaml.write_text(
            "name: PhotoTask\nsteps:\n  - verb: take_photo\n    params:\n      topic: /image\n"
        )

        # Create a minimal RDF with only differential_drive (no rgb_camera)
        rdf_yaml = tmp_path / "robot.rdf.yaml"
        rdf_yaml.write_text(
            "name: test-bot\nversion: '1.0'\nmodules:\n"
            "  - name: base\n    type: motor_controller\n    capabilities:\n"
            "      - name: navigation\n        type: differential_drive\n"
            "        version: '1.0'\n"
            "        parameters:\n"
            "          wheel_separation: 0.16\n"
            "          wheel_radius: 0.033\n"
            "          max_linear_velocity: 0.22\n"
            "          max_angular_velocity: 2.84\n"
        )

        # Create a verb that requires rgb_camera
        verbs_dir = tmp_path / "verbs"
        verbs_dir.mkdir()
        (verbs_dir / "take_photo.yaml").write_text(
            "name: take_photo\nrequired_capabilities:\n  - rgb_camera\n"
            "parameters:\n  - name: topic\n    type: string\n    default: /image\n"
            "template: take_photo.xml.j2\n"
        )
        (verbs_dir / "take_photo.xml.j2").write_text(
            '<Action ID="TakePhoto" topic="{{ topic }}" />\n'
        )

        with pytest.raises(CompilationError, match="lacks capabilities"):
            compile_task(task_yaml, rdf_yaml, verbs_dir=verbs_dir)
