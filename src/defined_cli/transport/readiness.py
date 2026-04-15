"""Readiness check data model and topic builder.

Defines the topic health contract: which topics MUST be publishing
for a given robot/task/world combination, and the result types for
reporting health status.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import yaml

_log = logging.getLogger(__name__)


@dataclass(frozen=True)
class TopicCheck:
    """A single topic to verify."""

    topic: str
    msg_type: str
    required: bool = True
    timeout: float = 10.0


@dataclass(frozen=True)
class TopicResult:
    """Outcome of checking one topic."""

    topic: str
    publishing: bool
    latency_ms: float | None
    error: str | None = None


@dataclass
class ReadinessReport:
    """Aggregate readiness result."""

    connected: bool
    topics: list[TopicResult]
    timestamp: datetime
    checks: list[TopicCheck] = field(default_factory=list)

    @property
    def ready(self) -> bool:
        """True if connected and all required topics are publishing."""
        if not self.connected:
            return False
        required_topics = {c.topic for c in self.checks if c.required}
        for result in self.topics:
            if result.topic in required_topics and not result.publishing:
                return False
        return True

    @property
    def failed(self) -> list[TopicResult]:
        """Topics that failed the check (required and not publishing)."""
        required_topics = {c.topic for c in self.checks if c.required}
        return [r for r in self.topics if r.topic in required_topics and not r.publishing]

    def summary(self) -> str:
        """Human-readable one-liner."""
        total = len(self.topics)
        healthy = sum(1 for r in self.topics if r.publishing)
        if healthy == total:
            return f"{healthy}/{total} topics OK"
        missing = [r.topic for r in self.failed]
        return f"{healthy}/{total} topics — {', '.join(missing)} MISSING"


CAPABILITY_TOPICS: dict[str, list[tuple[str, str]]] = {
    "base": [
        ("/rosout", "rcl_interfaces/Log"),
        ("/robot_description", "std_msgs/String"),
        ("/clock", "rosgraph_msgs/Clock"),
        ("/odom", "nav_msgs/Odometry"),
        ("/tf", "tf2_msgs/TFMessage"),
        ("/task_status", "std_msgs/String"),
    ],
    "navigate": [
        ("/map", "nav_msgs/OccupancyGrid"),
    ],
    "lidar": [
        ("/scan", "sensor_msgs/LaserScan"),
    ],
    "camera": [
        ("/camera/image_raw", "sensor_msgs/Image"),
        ("/camera/camera_info", "sensor_msgs/CameraInfo"),
    ],
}

_VERB_CAPABILITIES: dict[str, list[str]] = {
    "go_to": ["navigate"],
    "explore": ["navigate"],
    "capture_image": ["camera"],
}


def build_topic_checks(
    rdf_path: Path | None = None,
    task_path: Path | None = None,
    world_path: Path | None = None,
    bridge_config_path: Path | None = None,
) -> list[TopicCheck]:
    """Derive expected topics from robot config, task verbs, and bridge config."""
    capabilities: set[str] = {"base"}

    if rdf_path is not None:
        capabilities.update(_capabilities_from_rdf(rdf_path))
    else:
        capabilities.add("lidar")

    if task_path is not None:
        capabilities.update(_capabilities_from_task(task_path))
    else:
        capabilities.add("navigate")

    seen: set[str] = set()
    checks: list[TopicCheck] = []
    for cap in capabilities:
        for topic, msg_type in CAPABILITY_TOPICS.get(cap, []):
            if topic not in seen:
                seen.add(topic)
                checks.append(TopicCheck(topic=topic, msg_type=msg_type))

    return checks


def _capabilities_from_rdf(rdf_path: Path) -> set[str]:
    caps: set[str] = set()
    try:
        data = yaml.safe_load(rdf_path.read_text())
        for module in data.get("modules", []):
            for cap in module.get("capabilities", []):
                cap_type = cap.get("type", "")
                if cap_type == "rgb_camera":
                    caps.add("camera")
                elif cap_type == "lidar_2d":
                    caps.add("lidar")
    except Exception:
        _log.debug("Failed to parse RDF for readiness check", exc_info=True)
    return caps


def _capabilities_from_task(task_path: Path) -> set[str]:
    caps: set[str] = set()
    try:
        data = yaml.safe_load(task_path.read_text())
        for step in data.get("steps", []):
            verb = step.get("verb", "")
            for cap in _VERB_CAPABILITIES.get(verb, []):
                caps.add(cap)
    except Exception:
        _log.debug("Failed to parse task for readiness check", exc_info=True)
    return caps
