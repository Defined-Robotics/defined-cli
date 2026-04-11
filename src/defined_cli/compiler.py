"""Compiler wrapper — translates defined-compiler exceptions to user-facing errors.

This module wraps the ``defined-compiler`` Python API and catches every
exception that the underlying pipeline can throw:

- ``FileNotFoundError`` — missing task, RDF, or verb definition files
- ``yaml.YAMLError`` — malformed YAML syntax
- ``pydantic.ValidationError`` — invalid RDF schema
- ``jinja2.TemplateNotFound`` — missing verb template
- ``jinja2.TemplateSyntaxError`` — broken verb template
- ``ValueError`` — unknown verb name
- ``KeyError`` — missing required field in task YAML

Each exception is caught and re-raised as a ``CompilationError`` with
an actionable user-facing message and fix suggestion.

Usage:
    from defined_cli.compiler import compile_task

    xml_path = compile_task(
        task_yaml=Path("tasks/patrol.task.yaml"),
        rdf_yaml=Path("robot.rdf.yaml"),
    )
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, NoReturn

from .errors import CompilationError


@dataclass(frozen=True)
class StepInfo:
    """Metadata for a single task step, extracted at compile time."""

    verb: str  # original verb name, e.g. "go_to"
    label: str  # human-readable, e.g. "GoTo → (1.0, 0.0)"
    index: int  # 0-based position in the task


@dataclass(frozen=True)
class CompileResult:
    """Result of compiling a task YAML to BT XML."""

    xml_path: Path
    task_name: str
    steps: list[StepInfo] = field(default_factory=list)


def compile_task(
    task_yaml: Path,
    rdf_yaml: Path,
    verbs_dir: Path | None = None,
    output_dir: Path | None = None,
    *,
    param_overrides: dict[str, Any] | None = None,
) -> CompileResult:
    """Compile a task YAML to BT XML.

    Runs the full compilation pipeline: parse task → expand verbs →
    capability gate → emit BT XML. Writes the output file and
    returns a CompileResult with the path and step metadata.

    Args:
        task_yaml: Path to the task YAML file.
        rdf_yaml: Path to the robot RDF YAML file.
        verbs_dir: Directory containing verb YAML and Jinja2 template
            files. Defaults to the built-in verb library shipped
            with defined-compiler.
        output_dir: Directory to write the output XML. Created if it
            does not exist. Defaults to ``work/verb-compiler/build/``
            (the Docker volume mount point).
        param_overrides: Key/value pairs merged into every step's params
            at compile time. Matching keys override the task YAML value;
            unknown keys are silently ignored by the Jinja2 template.
            All values are strings — BT.CPP parses them from XML attributes.
            Example: ``{"timeout": "120", "retries": "5"}``.

    Returns:
        CompileResult with xml_path, task_name, and step metadata.

    Raises:
        CompilationError: On any compilation failure, with a
            user-facing message and fix suggestion.
    """
    # --- Validate input files exist ---
    _validate_inputs(task_yaml, rdf_yaml, verbs_dir)

    # --- Load robot definition ---
    robot = _load_rdf(rdf_yaml)

    # --- Compile task to BT XML ---
    task_name, xml, steps = _compile(task_yaml, rdf_yaml, robot, verbs_dir, param_overrides)

    # --- Write output file ---
    xml_path = _write_output(xml, task_name, output_dir)
    return CompileResult(xml_path=xml_path, task_name=task_name, steps=steps)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _validate_inputs(
    task_yaml: Path,
    rdf_yaml: Path,
    verbs_dir: Path | None,
) -> None:
    """Check that all input files and directories exist.

    Raises:
        CompilationError: If any input is missing.
    """
    if not task_yaml.exists():
        raise CompilationError(
            f"Task file not found: {task_yaml}",
            suggestion="Check the file path and try again.",
        )
    if not rdf_yaml.exists():
        raise CompilationError(
            f"Robot definition not found: {rdf_yaml}",
            suggestion="Check the --rdf path. Expected a .rdf.yaml file.",
        )
    if verbs_dir is not None and not verbs_dir.is_dir():
        raise CompilationError(
            f"Verbs directory not found: {verbs_dir}",
            suggestion="Check the --verbs-dir path.",
        )


def _load_rdf(rdf_yaml: Path) -> object:
    """Load and validate the robot RDF file.

    Args:
        rdf_yaml: Path to the robot RDF YAML file.

    Returns:
        Parsed ``Robot`` model instance.

    Raises:
        CompilationError: On YAML syntax errors, Pydantic validation
            failures, or missing files.
    """
    try:
        from defined_rdf.parser import load as load_rdf

        return load_rdf(rdf_yaml)
    except FileNotFoundError:
        raise CompilationError(
            f"Robot definition not found: {rdf_yaml}",
            suggestion="Check the --rdf path.",
        )
    except Exception as exc:
        _translate_rdf_error(exc, rdf_yaml)


def _compile(
    task_yaml: Path,
    rdf_yaml: Path,
    robot: object,
    verbs_dir: Path | None,
    param_overrides: dict[str, Any] | None = None,
) -> tuple[str, str, list[StepInfo]]:
    """Run the compilation pipeline: parse → expand → gate → emit.

    Returns:
        Tuple of (task_name, xml_string, steps).
    """
    try:
        from defined_rdf.registry import CapabilityRegistry

        from defined_compiler import bt_emitter, capability_gate, parser, verb_expander

        registry = CapabilityRegistry(robot)
        task = parser.load_task(task_yaml)

        expanded = []
        steps: list[StepInfo] = []
        for i, step in enumerate(task.get("steps", [])):
            verb_name = step["verb"]
            params = step.get("params", {})
            if param_overrides:
                params = {**params, **param_overrides}

            verb_data = verb_expander.expand_verb(
                verb_name, params, verbs_dir=verbs_dir
            )

            result = capability_gate.check(
                registry, verb_data["required_capabilities"]
            )
            if not result.passed:
                available = registry.list_types()
                raise CompilationError(
                    f"Robot '{robot.name}' lacks capabilities required by "
                    f"verb '{verb_name}': {result.missing}",
                    suggestion=(
                        f"Available capabilities: {available}. "
                        f"Add the missing ones to {rdf_yaml} or remove "
                        f"the verb from the task."
                    ),
                )

            expanded.append(verb_data)
            steps.append(_make_step_info(verb_name, params, i))

        task_name = task.get("name", "CompiledTask")
        xml = bt_emitter.render_bt_xml(
            expanded, task_name=task_name, verbs_dir=verbs_dir
        )
        return task_name, xml, steps

    except CompilationError:
        raise
    except FileNotFoundError as exc:
        raise CompilationError(
            f"File not found during compilation: {exc}",
            suggestion="Check that all referenced files exist.",
        ) from exc
    except ValueError as exc:
        # verb_expander raises ValueError for unknown verbs
        raise CompilationError(
            str(exc),
            suggestion="Check verb names in your task file. "
            "Use built-in verbs: go_to, wait, report.",
        ) from exc
    except KeyError as exc:
        raise CompilationError(
            f"Missing required field in task YAML: {exc}",
            suggestion="Each step needs 'verb' and optionally 'params'.",
        ) from exc
    except Exception as exc:
        _translate_compilation_error(exc)


def _write_output(xml: str, task_name: str, output_dir: Path | None) -> Path:
    """Write compiled XML to disk.

    Args:
        xml: The BT XML string to write.
        task_name: Task name, used as the output filename.
        output_dir: Target directory. Created if missing.

    Returns:
        Absolute path to the written file.
    """
    if output_dir is None:
        # Default: verb-compiler build/ (mounted as /bt_xml in Docker)
        output_dir = (
            Path(__file__).resolve().parent.parent.parent.parent
            / "verb-compiler"
            / "build"
        )
    output_dir.mkdir(parents=True, exist_ok=True)

    output_path = output_dir / f"{task_name}.xml"
    output_path.write_text(xml)
    return output_path


def _make_step_info(verb: str, params: dict, index: int) -> StepInfo:
    """Build a human-readable StepInfo from a verb name and its parameters."""
    # PascalCase action name (matches BT executor node names)
    action = "".join(w.capitalize() for w in verb.split("_"))

    # Build a short param summary for the label
    if verb == "go_to":
        x = params.get("x", "?")
        y = params.get("y", "?")
        label = f"{action} ({x}, {y})"
    elif verb == "wait":
        dur = params.get("duration", "?")
        label = f"{action} ({dur}s)"
    elif verb == "report":
        msg = params.get("message", "")
        label = f"{action}: {msg}" if msg else action
    else:
        label = action

    return StepInfo(verb=verb, label=label, index=index)


# ---------------------------------------------------------------------------
# Error translation
# ---------------------------------------------------------------------------


def _translate_rdf_error(exc: Exception, rdf_yaml: Path) -> NoReturn:
    """Translate RDF parsing exceptions to ``CompilationError``.

    Handles Pydantic ``ValidationError``, YAML ``ScannerError``,
    and unknown exceptions with appropriate user messages.

    Args:
        exc: The caught exception.
        rdf_yaml: Path to the RDF file (for error messages).

    Raises:
        CompilationError: Always.
    """
    exc_type = type(exc).__name__

    if "ValidationError" in exc_type:
        raise CompilationError(
            f"Invalid robot definition in {rdf_yaml}: {exc}",
            suggestion="Check the RDF YAML structure. "
            "See work/rdf/examples/ for reference.",
            detail=str(exc),
        ) from exc

    if "YAMLError" in exc_type or "ScannerError" in exc_type:
        raise CompilationError(
            f"YAML syntax error in {rdf_yaml}",
            suggestion="Check indentation and syntax. "
            "YAML is whitespace-sensitive.",
            detail=str(exc),
        ) from exc

    raise CompilationError(
        f"Failed to load robot definition: {exc}",
        suggestion=f"Check {rdf_yaml} for errors.",
        detail=str(exc),
    ) from exc


def _translate_compilation_error(exc: Exception) -> NoReturn:
    """Translate compilation exceptions to ``CompilationError``.

    Handles YAML errors, Jinja2 template errors, and unknown
    exceptions with appropriate user messages.

    Args:
        exc: The caught exception.

    Raises:
        CompilationError: Always.
    """
    exc_type = type(exc).__name__

    if "YAMLError" in exc_type or "ScannerError" in exc_type:
        raise CompilationError(
            f"YAML syntax error in task file: {exc}",
            suggestion="Check indentation and syntax.",
            detail=str(exc),
        ) from exc

    if "TemplateNotFound" in exc_type:
        raise CompilationError(
            f"Verb template not found: {exc}",
            suggestion="Check that the verb's .xml.j2 template "
            "exists in the verbs directory.",
            detail=str(exc),
        ) from exc

    if "TemplateSyntaxError" in exc_type:
        raise CompilationError(
            f"Verb template syntax error: {exc}",
            suggestion="Check the .xml.j2 template for "
            "Jinja2 syntax errors.",
            detail=str(exc),
        ) from exc

    raise CompilationError(
        f"Compilation failed: {exc}",
        suggestion="Run with --verbose for details.",
        detail=str(exc),
    ) from exc
