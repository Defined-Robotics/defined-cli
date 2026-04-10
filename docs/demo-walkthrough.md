# Demo Walkthrough: Explore → Mark POIs → Patrol

Step-by-step guide to the full Defined Robotics demo workflow.

## Prerequisites

- Docker Desktop running
- defined-cli installed: `pip install -e ".[dev,tui]"` from `work/cli/`
- Foxglove Studio: https://studio.foxglove.dev (or desktop app)

## Step 1: Start the Simulation

```bash
cd work/defined_platform/docker
docker compose up --build -d
```

Wait 2-4 minutes for Gazebo, Nav2, SLAM, and the BT executor to stabilize.
Check readiness:

```bash
docker compose logs -f sim 2>&1 | grep "Managed nodes are active"
```

## Step 2: Open Foxglove

Open Foxglove Studio and connect to `ws://localhost:8765`.

Import the provided layout for the best experience:

1. In Foxglove: Layout menu → Import layout
2. Select `work/cli/sample/foxglove/defined_demo.json`

This gives you:
- 3D panel with map, scan, and odometry visualization
- Publish panel pre-configured for `/clicked_point` (POI marking)
- Raw messages panel showing `/task_status` JSON
- Topic graph filtered to defined topics

## Step 3: Launch the TUI

```bash
cd work/cli
defined --rdf sample/robot.rdf.yaml
```

The TUI launches immediately and shows "Disconnected" while it connects to
rosbridge in the background. Once connected, the status bar turns green.

The TUI has three panels:
- **Mission** — active task steps and status
- **World** — POIs currently in state
- **Diagnostics** — robot diagnostics and topic health

Use the **command bar** at the bottom to submit tasks (type a task YAML path
and press Enter). Press `q` to quit.

## Step 4: Explore the Map

Submit the explore task from the TUI command bar:

```
Task YAML: sample/tasks/explore.task.yaml
```

Or run without TUI (standalone):

```bash
cd work/cli
defined compile sample/tasks/explore.task.yaml --rdf sample/robot.rdf.yaml
```

In Foxglove you'll see:
- The SLAM map building in real-time
- The robot navigating to frontier boundaries
- `/task_status` panel updating with exploration progress

Exploration completes when no more frontiers remain (map is fully built).

## Step 5: Mark Points of Interest

### Option A: Watch for map clicks (recommended for demo)

```bash
defined world watch
```

In Foxglove's 3D panel, click on locations in the map. Each click publishes
to `/clicked_point`. The CLI will prompt you for a name:

```
Watching for clicks on /clicked_point… (Ctrl+C to stop)

[click] (1.52, 2.01)  Name: survey-1  ✓ saved
[click] (3.05, 0.98)  Name: survey-2  ✓ saved
[click] (2.00, -1.00) Name: survey-3  ✓ saved
[click] (0.00, 0.00)  Name: dock      ✓ saved
^C  Saved 4 POIs.
```

### Option B: Robot's current position

Drive or navigate the robot to a location, then mark it:

```bash
defined world mark survey-1
defined world mark dock --type constant
```

### Option C: Manual coordinates

```bash
defined world add dock 0.0 0.0 --type constant
defined world add survey-1 1.5 2.0
defined world add survey-2 3.0 1.0
defined world add survey-3 -- 2.0 -1.0
```

Or use the convenience script:

```bash
bash sample/seed_world.sh
```

Note: negative coordinates require `--` separator before the values.

## Step 6: Verify POIs

```bash
defined world list
```

Should show all POIs with coordinates and types:

```
        Points of Interest
┌──────────┬───────┬───────┬──────────┬────────┐
│ Name     │     X │     Y │ Type     │ Radius │
├──────────┼───────┼───────┼──────────┼────────┤
│ dock     │ 0.000 │ 0.000 │ constant │    0.5 │
│ survey-1 │ 1.500 │ 2.000 │ static   │    0.5 │
│ survey-2 │ 3.000 │ 1.000 │ static   │    0.5 │
│ survey-3 │ 2.000 │-1.000 │ static   │    0.5 │
└──────────┴───────┴───────┴──────────┴────────┘
```

## Step 7: Run Patrol

Submit the patrol task from the TUI command bar (if TUI is still open):

```
Task YAML: sample/tasks/patrol_pois.task.yaml
```

Or launch a fresh TUI session with the patrol task pre-loaded:

```bash
defined --rdf sample/robot.rdf.yaml
```

The TUI shows:
- Robot status: IDLE → ON_MISSION
- Steps progressing through go_to/report pairs
- Reports appearing in the World panel as the robot visits each POI
- Mission completing with SUCCESS

## Step 8: Clean Up

```bash
cd work/defined_platform/docker
docker compose down -v
```

Use `-v` to clear cached build volumes if you've changed C++ code.

## Troubleshooting

**"POI reference could not be resolved"**
→ Run `defined world list` and check that POI names in your task YAML
match exactly. POI names are case-sensitive.

**"Connection refused" / TUI shows Disconnected**
→ Ensure the sim is running: `docker compose ps`
→ Check rosbridge: `curl -s http://localhost:9090` should connect

**Robot stuck during exploration**
→ Check Foxglove for costmap obstacles
→ Try restarting Nav2: `docker compose restart sim`

**Exploration never completes**
→ The explore verb has a 300s timeout by default
→ In confined spaces, increase timeout in `explore.task.yaml`

**TUI shows FAILURE**
→ Check `docker compose logs sim` for Nav2 errors
→ Ensure SLAM is running: look for `/map` topic in Foxglove
