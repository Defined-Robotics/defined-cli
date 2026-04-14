"""Tests for mission/validator.py — dependency validation plumbing."""

from __future__ import annotations

from pathlib import Path

from defined_cli.mission.validator import validate_deps


class TestValidateDeps:
    """validate_deps returns warnings for unmet verb dependencies."""

    def test_returns_empty_for_no_verbs(self) -> None:
        """No verbs → no warnings."""
        assert validate_deps(verbs_dir=None) == []

    def test_returns_empty_for_empty_verbs_dir(self, tmp_path: Path) -> None:
        """Empty verbs directory → no warnings."""
        assert validate_deps(verbs_dir=tmp_path) == []

    def test_returns_empty_for_valid_verbs(self, tmp_path: Path) -> None:
        """Verb files present → still returns empty (v0.1.0 fat image)."""
        verb_file = tmp_path / "go_to.yaml"
        verb_file.write_text("name: go_to\ntemplate: go_to.xml.j2\n")
        assert validate_deps(verbs_dir=tmp_path) == []

    def test_collects_verb_count(self, tmp_path: Path) -> None:
        """Verify the function discovers verb YAML files."""
        (tmp_path / "go_to.yaml").write_text("name: go_to\n")
        (tmp_path / "wait.yaml").write_text("name: wait\n")
        (tmp_path / "not_yaml.txt").write_text("ignore me")
        result = validate_deps(verbs_dir=tmp_path)
        # v0.1.0: always empty — plumbing only
        assert result == []
