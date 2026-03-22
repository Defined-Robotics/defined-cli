# defined-cli

Platform orchestrator for Defined Robotics. Compiles, deploys, and monitors robot tasks across simulation, hardware mocks, and real hardware.

## Quick Start

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e "../rdf" -e "../verb-compiler" -e ".[dev]"

# Compile a task
defined compile sample/tasks/patrol.task.yaml --rdf sample/robot.rdf.yaml

# Run tests
pytest
```

## Architecture

See the [plan](../../.claude/plans/velvet-crunching-cake.md) for full architecture details.
