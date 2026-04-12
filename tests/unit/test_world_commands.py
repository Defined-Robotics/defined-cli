"""Tests for world mark, world watch, and pose helper."""

from __future__ import annotations

import threading
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest
from click.testing import CliRunner

from defined_cli.main import cli
from defined_cli.state.store import StateStore


@pytest.fixture
def tmp_store(tmp_path):
    return StateStore(path=tmp_path / "state.yaml")


# ---------------------------------------------------------------------------
# Pose helper
# ---------------------------------------------------------------------------


class TestFetchRobotPose:

    @patch("defined_cli.transport.pose._get_reactor")
    @patch("defined_cli.transport.pose.roslibpy")
    def test_fetch_pose_returns_xy(self, mock_roslibpy, mock_reactor):
        """fetch_robot_pose returns (x, y) from a /amcl_pose message."""
        from defined_cli.transport.pose import fetch_robot_pose

        mock_ros = MagicMock()
        mock_ros.is_connected = True
        mock_roslibpy.Ros.return_value = mock_ros
        mock_ros.on_ready.side_effect = lambda cb: cb()

        mock_topic = MagicMock()
        mock_roslibpy.Topic.return_value = mock_topic

        # The real code calls reactor.callFromThread(topic.subscribe, callback)
        # so we need callFromThread to invoke the function immediately
        def call_immediately(fn, *args, **kwargs):
            fn(*args, **kwargs)

        mock_reactor.return_value.callFromThread.side_effect = call_immediately

        # When subscribe is called, deliver a pose message
        def fake_subscribe(callback):
            callback({
                "pose": {
                    "pose": {
                        "position": {"x": 1.5, "y": 2.0, "z": 0.0}
                    }
                }
            })

        mock_topic.subscribe.side_effect = fake_subscribe

        x, y = fetch_robot_pose(host="localhost", port=9090)
        assert x == pytest.approx(1.5)
        assert y == pytest.approx(2.0)

    @patch("defined_cli.transport.pose._get_reactor")
    @patch("defined_cli.transport.pose.roslibpy")
    def test_fetch_pose_timeout_raises(self, mock_roslibpy, mock_reactor):
        """fetch_robot_pose raises TimeoutError when no message arrives."""
        from defined_cli.transport.pose import fetch_robot_pose

        mock_ros = MagicMock()
        mock_ros.is_connected = True
        mock_roslibpy.Ros.return_value = mock_ros
        mock_ros.on_ready.side_effect = lambda cb: cb()

        def call_immediately(fn, *args, **kwargs):
            fn(*args, **kwargs)

        mock_reactor.return_value.callFromThread.side_effect = call_immediately

        mock_topic = MagicMock()
        mock_roslibpy.Topic.return_value = mock_topic
        # Subscribe but never call the callback
        mock_topic.subscribe.side_effect = lambda cb: None

        with pytest.raises(TimeoutError):
            fetch_robot_pose(host="localhost", port=9090, timeout=0.1)


# ---------------------------------------------------------------------------
# world mark
# ---------------------------------------------------------------------------


class TestWorldMark:

    @patch("defined_cli.main.StateStore")
    @patch("defined_cli.main.fetch_robot_pose", return_value=(1.5, 2.0))
    def test_mark_saves_poi(self, mock_fetch, mock_store_cls, tmp_path):
        """world mark captures pose and saves as POI."""
        store = StateStore(path=tmp_path / "state.yaml")
        mock_store_cls.return_value = store

        runner = CliRunner()
        result = runner.invoke(cli, ["world", "mark", "kitchen"])

        assert result.exit_code == 0
        assert "kitchen" in result.output

        snapshot = store.load()
        assert "kitchen" in snapshot.world.pois
        poi = snapshot.world.pois["kitchen"]
        assert poi["center"]["x"] == pytest.approx(1.5)
        assert poi["center"]["y"] == pytest.approx(2.0)

    @patch("defined_cli.main.StateStore")
    @patch("defined_cli.main.fetch_robot_pose", side_effect=TimeoutError("no pose"))
    def test_mark_shows_error_on_timeout(self, mock_fetch, mock_store_cls, tmp_path):
        """world mark shows error when pose fetch times out."""
        store = StateStore(path=tmp_path / "state.yaml")
        mock_store_cls.return_value = store

        runner = CliRunner()
        result = runner.invoke(cli, ["world", "mark", "kitchen"])

        assert result.exit_code != 0 or "error" in result.output.lower() or "timeout" in result.output.lower()


# ---------------------------------------------------------------------------
# world watch
# ---------------------------------------------------------------------------


class TestWorldWatch:

    def test_subscribe_clicked_point_calls_callback(self):
        """subscribe_clicked_point delivers (x, y) to callback."""
        from defined_cli.transport.pose import subscribe_clicked_point

        with patch("defined_cli.transport.pose._get_reactor") as mock_reactor, \
             patch("defined_cli.transport.pose.roslibpy") as mock_roslibpy:

            mock_ros = MagicMock()
            mock_ros.is_connected = True
            mock_roslibpy.Ros.return_value = mock_ros
            mock_ros.on_ready.side_effect = lambda cb: cb()

            def call_immediately(fn, *args, **kwargs):
                fn(*args, **kwargs)

            mock_reactor.return_value.callFromThread.side_effect = call_immediately

            received = []

            def capture(x, y):
                received.append((x, y))

            mock_topic = MagicMock()
            mock_roslibpy.Topic.return_value = mock_topic

            # Capture the subscribe callback and call it
            def fake_subscribe(callback):
                callback({"point": {"x": 3.0, "y": 4.0, "z": 0.0}})

            mock_topic.subscribe.side_effect = fake_subscribe

            ros, topic = subscribe_clicked_point(callback=capture)

            assert len(received) == 1
            assert received[0] == pytest.approx((3.0, 4.0))

    def test_watch_callback_saves_poi(self, tmp_path):
        """The watch callback logic correctly saves a POI to StateStore."""
        from defined_cli.state.blackboard import Blackboard

        store = StateStore(path=tmp_path / "state.yaml")

        # Simulate what the watch callback does
        snapshot = store.load()
        bb = Blackboard(data={"world": {"pois": snapshot.world.pois}})
        bb.set_poi("survey-1", (3.0, 4.0), radius=0.5, poi_type="static")
        snapshot.world.pois = bb.list_pois()
        store.save(snapshot)

        # Verify
        loaded = store.load()
        assert "survey-1" in loaded.world.pois
        assert loaded.world.pois["survey-1"]["center"]["x"] == pytest.approx(3.0)
