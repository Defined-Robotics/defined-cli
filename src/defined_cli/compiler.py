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

from pathlib import Path

from .errors import CompilationError


def compile_task(
    task_yaml: Path,
    rdf_yaml: Path,
    verbs_dir: Path | None = None,
    output_dir: Path | None = None,
) -> Path:
    """Compile a task YAML to BT XML.

    Runs the full compilation pipeline: parse task → expand verbs →
    capability gate → emit BT XML. Writes the output file and
    returns its path.

    Args:
        task_yaml: Path to the task YAML file.
        rdf_yaml: Path to the robot RDF YAML file.
        verbs_dir: Directory containing verb YAML and Jinja2 template
            files. Defaults to the built-in verb library shipped
            with defined-compiler.
        output_dir: Directory to write the output XML. Created if it
            does not exist. Defaults to ``work/verb-compiler/build/``
            (the Docker volume mount point).

    Returns:
        Absolute path to the generated BT XML file.

    Raises:
        CompilationError: On any compilation failure, with a
            user-facing message and fix suggestion.
    """
    # --- Validate input files exist ---
    _validate_inputs(task_yaml, rdf_yaml, verbs_dir)

    # --- Load robot definition ---
    robot = _load_rdf(rdf_yaml)

    # --- Compile task to BT XML ---
    task_name, xml = _compile(task_yaml, rdf_yaml, robot, verbs_dir)

    # --- Write output file ---
    return _write_output(xml, task_name, output_dir)


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
) -> tuple[str, str]:
    """Run the compilation pipeline: parse → expand → gate → emit.

    Args:
        task_yaml: Path to the task YAML file.
        rdf_yaml: Path to the RDF file (used in error messages).
        robot: Parsed ``Robot`` model instance.
        verbs_dir: Optional custom verbs directory.

    Returns:
        Tuple of (task_name, xml_string).

    Raises:
        CompilationError: On any pipeline failure.
    """
    try:
        from defined_rdf.registry import CapabilityRegistry

        from defined_compiler import bt_emitter, capability_gate, parser, verb_expander

        registry = CapabilityRegistry(robot)
        task = parser.load_task(task_yaml)

        expanded = []
        for step in task.get("steps", []):
            verb_name = step["verb"]
            params = step.get("params", {})

            verb_data = verb_expander.expand_verb(
                verb_name, params, verbs_dir=verbs_dir
            )

            result = capability_gate.check(
                registry, verb_data["required_capabilities"]
            )
            if not result.passed:
                available = registry.list_capabilities()
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

        task_name = task.get("name", "CompiledTask")
        xml = bt_emitter.render_bt_xml(
            expanded, task_name=task_name, verbs_dir=verbs_dir
        )
        return task_name, xml

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


# ---------------------------------------------------------------------------
# Error translation
# ---------------------------------------------------------------------------


def _translate_rdf_error(exc: Exception, rdf_yaml: Path) -> None:
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


def _translate_compilation_error(exc: Exception) -> None:
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
