# defined-cli

Unified mission control for Defined Robotics — compile tasks, manage POIs, and run missions through an interactive TUI.

## Quick Start

```bash
# Install
uv pip install -e ".[dev]"

# Launch the interactive TUI (connects to sim by default)
defined --rdf robot.rdf.yaml

# Compile a task (standalone, no TUI — for CI)
defined compile tasks/patrol.task.yaml --rdf robot.rdf.yaml

# Manage Points of Interest (scripting)
defined world add dock 0.0 0.0 --type constant
defined world add survey-1 1.5 2.0
defined world list
defined world mark dock          # mark robot's current position
defined world watch              # click-to-save from RViz/Foxglove
```

> **Note:** negative coordinates require the `--` separator:
> `defined world add name -- -1.0 3.5`

## TUI Commands

Once inside the TUI, type commands in the bottom bar:

| Command | Description |
|---------|-------------|
| `/run <task>` | Fuzzy-match a `*.task.yaml` and run it |
| `/stop` | Stop current mission |
| `/restart` | Re-run the last mission |
| `/world add <name> <x> <y>` | Add a POI |
| `/world list` | Show all POIs |
| `/world mark <name>` | Mark robot position as POI |
| `/teleop` | Toggle teleop mode (also auto-activates on panel focus) |
| `/status` | Connection + mission + POI summary |
| `/help` | Full command reference |
| `/quit` | Exit (must `/stop` first if mission running) |

**Keyboard shortcuts:** `1`/`2`/`3` focus panels, `d` cycles diagnostics detail, `/` focuses command bar, `q` quits.

## CLI Options

```
defined [OPTIONS] [COMMAND]

Options:
  --target [sim|hw]   Backend target (default: sim)
  --host TEXT         Rosbridge host (default: localhost)
  --port INTEGER      Rosbridge port (default: 9090)
  --rdf PATH          Robot RDF YAML
  --verbose           Show detailed error output
  --version           Show version
  --help              Show this message

Commands:
  compile   Compile a task YAML to BT XML (no TUI)
  world     Manage the world model (POIs, map data)
```

Running `defined` with no subcommand launches the interactive TUI.

## Architecture

```
defined-cli (Python, host, NO ROS2)
├── CLI Layer (Click) ────── main.py
├── Mission Control
│   ├── DefinedSession ───── mission/session.py   (unified API)
│   ├── Events ───────────── mission/events.py    (status enums, SessionEvent)
│   └── POI Resolver ─────── mission/resolver.py  ($world.pois.X expansion)
├── State Layer
│   ├── StateStore ───────── state/store.py       (~/.defined/state.yaml)
│   ├── Blackboard ───────── state/blackboard.py  (dot-path KV + POIs)
│   └── Models ───────────── state/model.py       (RobotState, WorldState, ...)
├── Compiler Wrapper ─────── compiler.py
├── Error System ─────────── errors.py
├── Protocols
│   ├── Target ────────── target/__init__.py
│   └── Transport ─────── transport/__init__.py
├── Implementations
│   ├── SimTarget ──────── target/sim.py          (docker compose)
│   └── RosbridgeTransport transport/rosbridge.py (roslibpy WebSocket)
└── TUI (Textual)
    ├── DefinedApp ─────── tui/defined_app.py     (app shell + key bindings)
    ├── CommandBar ─────── tui/command_bar.py      (parser, no TUI dep)
    └── Panels
        ├── StatusBar ──── tui/panels/status_bar.py
        ├── MissionPanel ─ tui/panels/mission.py
        ├── WorldPanel ─── tui/panels/world.py
        └── DiagnosticsPanel tui/panels/diagnostics.py
```

**DefinedSession** is the single API that replaces the old Orchestrator + MissionController. It owns the full lifecycle: connect, compile, deploy, monitor, reconnect. Thread-safe, observer-based events.

**Design constraint:** No ROS2 imports anywhere (DR-010). Communication is via rosbridge WebSocket only.

**Extraction boundary:** `state/` and `mission/` have zero imports from `click`, `rich`, or `textual` so they can be moved to `defined-core` in Milestone 2 without modification.

## State & World Model

State is persisted atomically to `~/.defined/state.yaml` on every transition.

```
~/.defined/state.yaml
├── robot:
│   ├── status: OFFLINE | IDLE | ON_MISSION | ERROR
│   └── current_mission: <task name> | null
├── world:
│   └── pois:
│       └── <name>: {center: {x, y}, radius, type: constant|static|dynamic}
└── history: [MissionRecord, ...]
```

POI references in task YAML (`$world.pois.dock`) are resolved at compile time by `mission/resolver.py`.

## E2E: Running Locally

### Prerequisites

1. Docker Desktop running
2. `uv` installed (`brew install uv` or `pip install uv`)
3. X11 forwarding for Gazebo GUI (optional — headless works fine)

### Step 1: Start the simulation stack

```bash
cd work/defined_platform/
docker compose -f docker/docker-compose.yml up --build
```

Wait for rosbridge to be ready (log line: `Rosbridge WebSocket server started on port 9090`).

### Step 2: Seed POIs (first time only)

```bash
cd work/cli/
source .venv/bin/activate

defined world add dock 0.0 0.0 --type constant
defined world add survey-1 1.5 2.0
defined world add survey-2 3.0 -1.0
defined world add survey-3 -2.0 1.5
defined world list
```

### Step 3: Launch the TUI

```bash
defined --rdf sample/robot.rdf.yaml
```

The TUI connects to rosbridge on `localhost:9090`. If the sim isn't running yet, the status bar shows "Disconnected" — the TUI won't crash.

### Step 4: Run a mission

In the TUI command bar, type:

```
/run patrol
```

This fuzzy-matches `sample/tasks/patrol.task.yaml`, compiles it (resolving `$world.pois.*`), deploys the BT XML to the executor, and monitors progress. The mission panel shows step-by-step progress with icons.

Other things to try:
- `/world add checkpoint 2.0 3.0` — add a POI from the TUI
- `/status` — see connection + mission state
- `/stop` — abort a running mission
- `/restart` — re-run the last mission
- `d` key — cycle diagnostics detail (messages -> suggestions -> full detail)

### Step 5: Clean up

```
/quit
```

Then stop the sim:

```bash
cd work/defined_platform/
docker compose -f docker/docker-compose.yml down -v
```

> **Tip:** Use `docker compose down -v` (with `-v`) to clear the cached build volume if you've changed C++ code or launch files.

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
    def fetch_pose(self) -> tuple[float, float]: ...  # robot pose from /odom

    @property
    def is_connected(self) -> bool: ...
```

## Testing

```bash
cd work/cli/
source .venv/bin/activate
pytest tests/ -v
```

Test structure:
- `tests/unit/` — mocked unit tests (events, session, command bar, panels, compiler)
- `tests/integration/` — CLI runner tests with real compiler
