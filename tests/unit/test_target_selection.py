"""Tests for target selection logic based on manifest.

Covers:
- Manifest with sim.image → DockerImageTarget
- Manifest without sim section → SimTarget (default)
- No manifest → SimTarget (backward compat)
- World env and custom port passed through to DockerImageTarget
"""

from __future__ import annotations

from pathlib import Path

import pytest

from defined_cli.launcher import select_target
from defined_cli.manifest import ProjectManifest
from defined_cli.target.docker_image import DockerImageTarget
from defined_cli.target.sim import SimTarget


class TestTargetSelection:

    def test_manifest_with_sim_image_uses_docker_image_target(self) -> None:
        """Preconditions: Manifest has sim.image set.
        Tests: select_target returns DockerImageTarget when sim config present.
        Success: Returned target is DockerImageTarget with correct image.
        """
        manifest = ProjectManifest.model_validate({
            "project": {"name": "test"},
            "robot": {"rdf": "robot.rdf.yaml"},
            "sim": {"image": "ghcr.io/defined-robotics/sim:0.1.0"},
        })

        target = select_target(manifest=manifest)
        assert isinstance(target, DockerImageTarget)
        assert target._image == "ghcr.io/defined-robotics/sim:0.1.0"

    def test_manifest_with_sim_and_world_env(self) -> None:
        """Preconditions: Manifest has sim.image; world_env provided.
        Tests: World environment is forwarded to DockerImageTarget.
        Success: target._world_env equals the provided value.
        """
        manifest = ProjectManifest.model_validate({
            "project": {"name": "test"},
            "robot": {"rdf": "robot.rdf.yaml"},
            "sim": {"image": "ghcr.io/defined-robotics/sim:0.1.0"},
        })

        target = select_target(manifest=manifest, world_env="warehouse")
        assert isinstance(target, DockerImageTarget)
        assert target._world_env == "warehouse"

    def test_manifest_without_sim_uses_sim_target(self) -> None:
        """Preconditions: Manifest exists but has no sim section.
        Tests: select_target falls back to SimTarget.
        Success: Returned target is SimTarget.
        """
        manifest = ProjectManifest.model_validate({
            "project": {"name": "test"},
            "robot": {"rdf": "robot.rdf.yaml"},
        })

        target = select_target(manifest=manifest)
        assert isinstance(target, SimTarget)

    def test_no_manifest_uses_sim_target(self) -> None:
        """Preconditions: No manifest provided (None).
        Tests: select_target defaults to SimTarget for backward compat.
        Success: Returned target is SimTarget.
        """
        target = select_target(manifest=None)
        assert isinstance(target, SimTarget)

    def test_manifest_with_sim_and_custom_port(self) -> None:
        """Preconditions: Manifest has sim.image; custom port provided.
        Tests: Custom port is forwarded to DockerImageTarget.
        Success: target._port equals the custom value.
        """
        manifest = ProjectManifest.model_validate({
            "project": {"name": "test"},
            "robot": {"rdf": "robot.rdf.yaml"},
            "sim": {"image": "my-image:latest"},
        })

        target = select_target(manifest=manifest, port=9091)
        assert isinstance(target, DockerImageTarget)
        assert target._port == 9091

    def test_manifest_with_sim_and_bt_xml_dir(self) -> None:
        """Preconditions: Manifest has sim.image; bt_xml_dir provided.
        Tests: BT XML host directory is forwarded to DockerImageTarget.
        Success: target._bt_xml_dir equals the provided path.
        """
        manifest = ProjectManifest.model_validate({
            "project": {"name": "test"},
            "robot": {"rdf": "robot.rdf.yaml"},
            "sim": {"image": "my-image:latest"},
        })

        target = select_target(manifest=manifest, bt_xml_dir=Path("/tmp/bt"))
        assert isinstance(target, DockerImageTarget)
        assert target._bt_xml_dir == Path("/tmp/bt")
