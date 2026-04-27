"""Tests for the ``defined sim pull`` smoke-test subcommand."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from defined_cli.main import cli


class TestSimPullCommand:
    """``defined sim pull`` invokes ``DockerImageTarget.pull_image``
    without launching the TUI."""

    def test_pull_with_explicit_image(self) -> None:
        """``--image`` short-circuits manifest lookup and pulls directly."""
        with patch("defined_cli.target.docker_image.DockerImageTarget") as TargetCls:
            instance = MagicMock()
            TargetCls.return_value = instance

            result = CliRunner().invoke(cli, ["sim", "pull", "--image", "ghcr.io/x/y:1.0"])

        assert result.exit_code == 0, result.output
        TargetCls.assert_called_once_with(image="ghcr.io/x/y:1.0")
        instance.pull_image.assert_called_once_with()

    def test_pull_errors_without_image_or_manifest(self) -> None:
        """No ``--image`` and no manifest with ``sim.image`` → exit 1 with hint."""
        result = CliRunner().invoke(cli, ["sim", "pull"])

        assert result.exit_code == 1
        assert "No image to pull" in result.output or "No image to pull" in result.stderr

    def test_pull_uses_manifest_image(self, tmp_path) -> None:
        """When ``--image`` is omitted, image is read from manifest's sim.image."""
        manifest_yaml = tmp_path / "defined.yaml"
        manifest_yaml.write_text(
            "project:\n"
            "  name: smoke\n"
            "robot:\n"
            "  rdf: robot.rdf.yaml\n"
            "sim:\n"
            "  image: ghcr.io/from-manifest:1.0\n"
        )
        # The manifest loader resolves rdf path; create a stub so validation passes.
        (tmp_path / "robot.rdf.yaml").write_text("name: stub\n")

        with patch("defined_cli.target.docker_image.DockerImageTarget") as TargetCls:
            instance = MagicMock()
            TargetCls.return_value = instance

            result = CliRunner().invoke(
                cli, ["sim", "pull", "--manifest", str(manifest_yaml)]
            )

        assert result.exit_code == 0, result.output
        TargetCls.assert_called_once_with(image="ghcr.io/from-manifest:1.0")
        instance.pull_image.assert_called_once_with()
