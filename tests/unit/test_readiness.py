"""Tests for readiness check data model and topic builder."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from defined_cli.transport.readiness import (
    TopicCheck,
    TopicResult,
    ReadinessReport,
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

    def _make_report(self, results, connected=True):
        return ReadinessReport(
            connected=connected,
            topics=results,
            timestamp=datetime.now(timezone.utc),
        )

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
