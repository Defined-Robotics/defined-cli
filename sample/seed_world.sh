#!/usr/bin/env bash
set -euo pipefail
# Seed default POIs for the patrol demo.
# Usage: bash sample/seed_world.sh
#
# These coordinates match the maze_10x10 Gazebo world.
# For real-world use, prefer: defined world watch (click on map)
#                          or: defined world mark  (robot's current pose)

defined world add dock 0.0 0.0 --type constant
defined world add survey-1 1.5 2.0
defined world add survey-2 3.0 1.0
defined world add survey-3 -- 2.0 -1.0

echo "4 POIs seeded. Run: defined world list"
