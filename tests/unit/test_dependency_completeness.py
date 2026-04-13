"""Guard test — every third-party import in defined_cli must be declared in pyproject.toml.

Catches the case where code imports a package (e.g. textual, pydantic) but
the dependency is missing from pyproject.toml, causing ModuleNotFoundError
when users install from a wheel.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

try:
    import tomllib
except ImportError:
    import tomli as tomllib  # type: ignore[no-redefine]

_CLI_ROOT = Path(__file__).resolve().parent.parent.parent
_SRC_ROOT = _CLI_ROOT / "src" / "defined_cli"
_PYPROJECT = _CLI_ROOT / "pyproject.toml"

# Mapping from import name → PyPI distribution name where they differ.
_IMPORT_TO_DIST: dict[str, str] = {
    "yaml": "pyyaml",
    "docker": "docker",
    "roslibpy": "roslibpy",
    "pydantic": "pydantic",
    "PIL": "pillow",
}

# Standard library top-level module names (Python 3.12+) and first-party
# packages that should be ignored.
_STDLIB = set(sys.stdlib_module_names)
_FIRST_PARTY = {"defined_cli", "defined_compiler", "defined_rdf"}

# Transitive deps that are imported directly but don't need their own
# pyproject.toml entry because they're pulled in by a declared dependency.
_TRANSITIVE = {"twisted"}  # pulled in by roslibpy


def _discover_internal_packages() -> set[str]:
    """Return names of all sub-packages/modules inside defined_cli src."""
    internal = set()
    for p in _SRC_ROOT.iterdir():
        if p.is_dir() and (p / "__init__.py").exists():
            internal.add(p.name)
        elif p.suffix == ".py" and p.name != "__init__.py":
            internal.add(p.stem)
    return internal


def _declared_dependencies() -> set[str]:
    """Parse pyproject.toml and return normalized dependency names."""
    raw = _PYPROJECT.read_text()
    data = tomllib.loads(raw)
    deps = data.get("project", {}).get("dependencies", [])
    # Normalize: "click>=8.0" → "click", "defined-compiler>=0.0.1" → "defined-compiler"
    names = set()
    for dep in deps:
        # Strip version specifiers and extras
        name = dep.split(">=")[0].split("<=")[0].split("==")[0].split("!=")[0]
        name = name.split("[")[0].strip().lower().replace("-", "_")
        names.add(name)
    return names


def _collect_imports(source: str) -> set[str]:
    """Return all top-level imported module names from a Python source string."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return set()
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module and not node.level:  # skip relative imports
                names.add(node.module.split(".")[0])
    return names


def _all_src_imports() -> set[str]:
    """Collect every unique top-level import across all source files."""
    all_imports: set[str] = set()
    for py_file in _SRC_ROOT.rglob("*.py"):
        all_imports |= _collect_imports(py_file.read_text())
    return all_imports


class TestDependencyCompleteness:

    def test_all_third_party_imports_declared(self):
        """Every third-party import used in src/ has a matching pyproject.toml dependency."""
        declared = _declared_dependencies()
        src_imports = _all_src_imports()

        # Filter to third-party only (exclude stdlib, first-party, internal, and transitive)
        internal = _discover_internal_packages()
        third_party = src_imports - _STDLIB - _FIRST_PARTY - internal - _TRANSITIVE

        missing = []
        for imp in sorted(third_party):
            # Map import name to distribution name
            dist_name = _IMPORT_TO_DIST.get(imp, imp).lower().replace("-", "_")
            if dist_name not in declared:
                missing.append(f"{imp} (expected '{dist_name}' in dependencies)")

        assert missing == [], (
            f"Third-party imports missing from pyproject.toml dependencies:\n"
            + "\n".join(f"  - {m}" for m in missing)
        )

    def test_core_imports_succeed(self):
        """Smoke test — key third-party packages are actually importable."""
        import click
        import docker
        import pydantic
        import rich
        import roslibpy
        import textual
        import yaml
