"""Tests for readiness check data model and topic builder."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from pathlib import Path

from defined_cli.transport.readiness import (
    TopicCheck,
    TopicResult,
    ReadinessReport,
    build_topic_checks,
    CAPABILITY_TOPICS,
)


class TestTopicCheck:

    def test_defaults(self):
        check = TopicCheck(topic="/odom", msg_type="nav_msgs/Odometry")
        assert check.topic == "/odom"
        assert check.msg_type == "nav_msgs/Odometry"
        assert check.required is True
        assert check.timeout == 10.0

    def test_optional_topic(self):
        check = TopicCheck(
            topic="/camera/image_raw",
            msg_type="sensor_msgs/Image",
            required=False,
        )
        assert check.required is False


class TestTopicResult:

    def test_healthy_result(self):
        result = TopicResult(
            topic="/odom", publishing=True, latency_ms=15.0, error=None,
        )
        assert result.publishing is True
        assert result.latency_ms == 15.0

    def test_failed_result(self):
        result = TopicResult(
            topic="/map", publishing=False, latency_ms=None,
            error="timeout (10s)",
        )
        assert result.publishing is False
        assert result.error is not None


class TestReadinessReport:

    def test_ready_when_all_required_publishing(self):
        checks = [
            TopicCheck(topic="/odom", msg_type="nav_msgs/Odometry"),
            TopicCheck(topic="/scan", msg_type="sensor_msgs/LaserScan"),
        ]
        results = [
            TopicResult(topic="/odom", publishing=True, latency_ms=10.0, error=None),
            TopicResult(topic="/scan", publishing=True, latency_ms=20.0, error=None),
        ]
        report = ReadinessReport(
            connected=True,
            topics=results,
            timestamp=datetime.now(timezone.utc),
            checks=checks,
        )
        assert report.ready is True
        assert report.failed == []

    def test_not_ready_when_required_missing(self):
        checks = [
            TopicCheck(topic="/odom", msg_type="nav_msgs/Odometry"),
            TopicCheck(topic="/map", msg_type="nav_msgs/OccupancyGrid"),
        ]
        results = [
            TopicResult(topic="/odom", publishing=True, latency_ms=10.0, error=None),
            TopicResult(topic="/map", publishing=False, latency_ms=None, error="timeout"),
        ]
        report = ReadinessReport(
            connected=True,
            topics=results,
            timestamp=datetime.now(timezone.utc),
            checks=checks,
        )
        assert report.ready is False
        assert len(report.failed) == 1
        assert report.failed[0].topic == "/map"

    def test_ready_when_optional_missing(self):
        checks = [
            TopicCheck(topic="/odom", msg_type="nav_msgs/Odometry"),
            TopicCheck(topic="/camera/image_raw", msg_type="sensor_msgs/Image", required=False),
        ]
        results = [
            TopicResult(topic="/odom", publishing=True, latency_ms=10.0, error=None),
            TopicResult(topic="/camera/image_raw", publishing=False, latency_ms=None, error="timeout"),
        ]
        report = ReadinessReport(
            connected=True,
            topics=results,
            timestamp=datetime.now(timezone.utc),
            checks=checks,
        )
        assert report.ready is True

    def test_not_ready_when_disconnected(self):
        report = ReadinessReport(
            connected=False,
            topics=[],
            timestamp=datetime.now(timezone.utc),
            checks=[],
        )
        assert report.ready is False

    def test_summary_all_healthy(self):
        checks = [
            TopicCheck(topic="/odom", msg_type="nav_msgs/Odometry"),
        ]
        results = [
            TopicResult(topic="/odom", publishing=True, latency_ms=10.0, error=None),
        ]
        report = ReadinessReport(
            connected=True, topics=results, checks=checks,
            timestamp=datetime.now(timezone.utc),
        )
        assert "1/1" in report.summary()

    def test_summary_with_failures(self):
        checks = [
            TopicCheck(topic="/odom", msg_type="nav_msgs/Odometry"),
            TopicCheck(topic="/map", msg_type="nav_msgs/OccupancyGrid"),
        ]
        results = [
            TopicResult(topic="/odom", publishing=True, latency_ms=10.0, error=None),
            TopicResult(topic="/map", publishing=False, latency_ms=None, error="timeout"),
        ]
        report = ReadinessReport(
            connected=True, topics=results, checks=checks,
            timestamp=datetime.now(timezone.utc),
        )
        s = report.summary()
        assert "1/2" in s
        assert "/map" in s


class TestCapabilityTopics:

    def test_base_includes_rosout(self):
        base = CAPABILITY_TOPICS["base"]
        topics = [t for t, _ in base]
        assert "/rosout" in topics

    def test_base_includes_robot_description(self):
        base = CAPABILITY_TOPICS["base"]
        topics = [t for t, _ in base]
        assert "/robot_description" in topics

    def test_base_includes_clock_odom_tf_task_status(self):
        base = CAPABILITY_TOPICS["base"]
        topics = [t for t, _ in base]
        assert "/clock" in topics
        assert "/odom" in topics
        assert "/tf" in topics
        assert "/task_status" in topics

    def test_navigate_includes_map(self):
        nav = CAPABILITY_TOPICS["navigate"]
        topics = [t for t, _ in nav]
        assert "/map" in topics

    def test_lidar_includes_scan(self):
        lidar = CAPABILITY_TOPICS["lidar"]
        topics = [t for t, _ in lidar]
        assert "/scan" in topics

    def test_camera_includes_image_and_info(self):
        cam = CAPABILITY_TOPICS["camera"]
        topics = [t for t, _ in cam]
        assert "/camera/image_raw" in topics
        assert "/camera/camera_info" in topics


class TestBuildTopicChecks:

    def test_no_args_returns_default_set(self):
        """No args = base + nav + lidar (common sim case)."""
        checks = build_topic_checks()
        topics = [c.topic for c in checks]
        assert "/rosout" in topics
        assert "/robot_description" in topics
        assert "/clock" in topics
        assert "/odom" in topics
        assert "/tf" in topics
        assert "/task_status" in topics
        assert "/map" in topics
        assert "/scan" in topics
        assert "/camera/image_raw" not in topics

    def test_rdf_with_camera_adds_camera_topics(self, tmp_path):
        rdf = tmp_path / "cam_robot.rdf.yaml"
        rdf.write_text(
            "name: cam_bot\nversion: '0.0.1'\n"
            "modules:\n"
            "  - name: camera\n"
            "    type: sensor\n"
            "    capabilities:\n"
            "      - name: rgb_camera\n"
            "        type: rgb_camera\n"
            "        parameters:\n"
            "          width: 640\n"
        )
        checks = build_topic_checks(rdf_path=rdf)
        topics = [c.topic for c in checks]
        assert "/camera/image_raw" in topics
        assert "/camera/camera_info" in topics

    def test_rdf_without_camera_skips_camera_topics(self, tmp_path):
        rdf = tmp_path / "lidar_robot.rdf.yaml"
        rdf.write_text(
            "name: lidar_bot\nversion: '0.0.1'\n"
            "modules:\n"
            "  - name: lidar\n"
            "    type: sensor\n"
            "    capabilities:\n"
            "      - name: lidar_2d\n"
            "        type: lidar_2d\n"
            "        parameters:\n"
            "          range_max: 3.5\n"
        )
        checks = build_topic_checks(rdf_path=rdf)
        topics = [c.topic for c in checks]
        assert "/camera/image_raw" not in topics
        assert "/scan" in topics

    def test_task_with_navigate_verb_includes_map(self, tmp_path):
        task = tmp_path / "patrol.task.yaml"
        task.write_text(
            "name: patrol\n"
            "steps:\n"
            "  - verb: go_to\n"
            "    params: {x: 1.0, y: 0.0}\n"
        )
        checks = build_topic_checks(task_path=task)
        topics = [c.topic for c in checks]
        assert "/map" in topics

    def test_task_without_navigate_verb_skips_map(self, tmp_path):
        task = tmp_path / "wait_only.task.yaml"
        task.write_text(
            "name: idle\n"
            "steps:\n"
            "  - verb: wait\n"
            "    params: {duration: 5}\n"
        )
        checks = build_topic_checks(task_path=task)
        topics = [c.topic for c in checks]
        assert "/map" not in topics

    def test_task_with_capture_image_adds_camera(self, tmp_path):
        task = tmp_path / "snap.task.yaml"
        task.write_text(
            "name: snap\n"
            "steps:\n"
            "  - verb: capture_image\n"
            "    params: {}\n"
        )
        checks = build_topic_checks(task_path=task)
        topics = [c.topic for c in checks]
        assert "/camera/image_raw" in topics

    def test_deduplicates_topics(self, tmp_path):
        rdf = tmp_path / "cam_robot.rdf.yaml"
        rdf.write_text(
            "name: cam_bot\nversion: '0.0.1'\n"
            "modules:\n"
            "  - name: camera\n"
            "    type: sensor\n"
            "    capabilities:\n"
            "      - name: rgb_camera\n"
            "        type: rgb_camera\n"
            "        parameters:\n"
            "          width: 640\n"
        )
        task = tmp_path / "snap.task.yaml"
        task.write_text(
            "name: snap\nsteps:\n  - verb: capture_image\n    params: {}\n"
        )
        checks = build_topic_checks(rdf_path=rdf, task_path=task)
        topics = [c.topic for c in checks]
        assert topics.count("/camera/image_raw") == 1

    def test_all_checks_are_topic_check_instances(self):
        checks = build_topic_checks()
        for c in checks:
            assert isinstance(c, TopicCheck)
