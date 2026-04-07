"""Guard tests -- state/ and mission/ must have zero CLI-specific imports.

These modules will be extracted to a shared library (defined-core) in
Milestone 2. They must not depend on click, rich, or textual.
"""

from __future__ import annotations

import ast
from pathlib import Path

_SRC_ROOT = Path(__file__).resolve().parent.parent.parent / "src" / "defined_cli"
_FORBIDDEN = {"click", "rich", "textual"}


def _collect_imports(source: str) -> set[str]:
    """Parse a Python source string and return all top-level imported module names."""
    tree = ast.parse(source)
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                names.add(node.module.split(".")[0])
    return names


def _check_package(package_dir: Path) -> list[str]:
    """Return a list of violations (file:module pairs) for a package directory."""
    violations = []
    for py_file in package_dir.rglob("*.py"):
        imports = _collect_imports(py_file.read_text())
        bad = imports & _FORBIDDEN
        if bad:
            rel = py_file.relative_to(_SRC_ROOT)
            violations.append(f"{rel} imports {bad}")
    return violations


class TestNoCLIImports:

    def test_state_modules_have_no_cli_imports(self):
        violations = _check_package(_SRC_ROOT / "state")
        assert violations == [], f"CLI imports found in state/: {violations}"

    def test_mission_modules_have_no_cli_imports(self):
        violations = _check_package(_SRC_ROOT / "mission")
        assert violations == [], f"CLI imports found in mission/: {violations}"
