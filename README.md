# defined-cli

Platform orchestrator for Defined Robotics — compile, deploy, and monitor robot tasks.

## Quick Start

```bash
# Install
pip install -e .          # core
pip install -e ".[tui]"   # with TUI display

# Compile a task
defined compile tasks/patrol.task.yaml --rdf robot.rdf.yaml

# Run (compile + deploy + monitor)
defined run tasks/patrol.task.yaml --rdf robot.rdf.yaml

# Run with full-screen TUI
defined run tasks/patrol.task.yaml --rdf robot.rdf.yaml --tui

# Check backend status
defined status

# Stop the backend
defined stop
```

## Architecture

```
defined-cli (Python, host, NO ROS2)
├── CLI Layer (Click) ────── main.py
├── Orchestrator ─────────── orchestrator.py
├── Compiler Wrapper ─────── compiler.py
├── Error System ─────────── errors.py
├── Protocols
│   ├── Target ────────── target/__init__.py
│   ├── Transport ─────── transport/__init__.py
│   └── Display ──────── display/__init__.py
└── Implementations
    ├── SimTarget ──────── target/sim.py (docker compose)
    ├── RosbridgeTransport transport/rosbridge.py (roslibpy WebSocket)
    ├── RichDisplay ────── display/rich.py (inline console)
    └── TuiDisplay ─────── tui/app.py (full-screen Textual)
```

**Pipeline:** start backend → check readiness → connect transport → compile task → deploy BT XML → monitor execution

**Design constraint:** No ROS2 imports anywhere (DR-010). Communication is via rosbridge WebSocket only.

## Extending

### Add a new Target (e.g., hardware)

```python
from defined_cli.target import TargetBase, TargetStatus

class HardwareTarget(TargetBase):
    def start(self) -> None: ...
    def stop(self) -> None: ...
    def status(self) -> TargetStatus: ...
    def resolve_xml_path(self, host_path: Path) -> str: ...
```

### Add a new Transport

```python
from defined_cli.transport import TransportBase, TaskProgress

class ZenohTransport(TransportBase):
    def connect(self) -> None: ...
    def disconnect(self) -> None: ...
    def send_task(self, bt_xml_path: str) -> None: ...
    def subscribe_status(self, callback) -> None: ...
    def wait_ready(self, timeout: float = 10.0) -> bool: ...
```

### Add a new Display

```python
from defined_cli.display import DisplayBase

class WebDisplay(DisplayBase):
    def set_steps(self, steps) -> None: ...
    def show_phase(self, phase, message) -> None: ...
    def show_progress(self, progress) -> None: ...
    def show_error(self, error) -> None: ...
    def show_success(self, message) -> None: ...
```

## Testing

```bash
pip install -e ".[dev,tui]"
pytest tests/ -v
```

Test structure:
- `tests/unit/` — mocked unit tests for each module
- `tests/integration/` — e2e tests with real compiler + CLI runner
