"""Tests for target selection logic based on manifest.

Covers:
- Manifest with sim.image → DockerImageTarget
- Manifest without sim section → SimTarget (default)
- No manifest → SimTarget (backward compat)
- World env passed through to DockerImageTarget
"""

from __future__ import annotations

from pathlib import Path

import pytest

from defined_cli.main import _select_target
from defined_cli.manifest import ProjectManifest
from defined_cli.target.docker_image import DockerImageTarget
from defined_cli.target.sim import SimTarget


class TestTargetSelection:

    def test_manifest_with_sim_image_uses_docker_image_target(self) -> None:
        """When manifest has sim.image, DockerImageTarget is selected."""
        manifest = ProjectManifest.model_validate({
            "project": {"name": "test"},
            "robot": {"rdf": "robot.rdf.yaml"},
            "sim": {"image": "ghcr.io/defined-robotics/sim:0.1.0"},
        })

        target = _select_target(manifest=manifest, target_flag="sim")
        assert isinstance(target, DockerImageTarget)
        assert target._image == "ghcr.io/defined-robotics/sim:0.1.0"

    def test_manifest_with_sim_and_world_env(self) -> None:
        """World environment is passed to DockerImageTarget."""
        manifest = ProjectManifest.model_validate({
            "project": {"name": "test"},
            "robot": {"rdf": "robot.rdf.yaml"},
            "sim": {"image": "ghcr.io/defined-robotics/sim:0.1.0"},
        })

        target = _select_target(
            manifest=manifest,
            target_flag="sim",
            world_env="warehouse",
        )
        assert isinstance(target, DockerImageTarget)
        assert target._world_env == "warehouse"

    def test_manifest_without_sim_uses_sim_target(self) -> None:
        """When manifest has no sim section, SimTarget is used."""
        manifest = ProjectManifest.model_validate({
            "project": {"name": "test"},
            "robot": {"rdf": "robot.rdf.yaml"},
        })

        target = _select_target(manifest=manifest, target_flag="sim")
        assert isinstance(target, SimTarget)

    def test_no_manifest_uses_sim_target(self) -> None:
        """When no manifest exists, SimTarget is used (backward compat)."""
        target = _select_target(manifest=None, target_flag="sim")
        assert isinstance(target, SimTarget)

    def test_manifest_with_sim_and_custom_port(self) -> None:
        """Custom port is passed to DockerImageTarget."""
        manifest = ProjectManifest.model_validate({
            "project": {"name": "test"},
            "robot": {"rdf": "robot.rdf.yaml"},
            "sim": {"image": "my-image:latest"},
        })

        target = _select_target(manifest=manifest, target_flag="sim", port=9091)
        assert isinstance(target, DockerImageTarget)
        assert target._port == 9091
