"""Tests for RosbridgeTransport — WebSocket communication via roslibpy."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from defined_cli.errors import TransportConnectionError as DefinedConnectionError
from defined_cli.transport import TaskProgress
from defined_cli.transport.rosbridge import RosbridgeTransport


@pytest.fixture
def transport() -> RosbridgeTransport:
    return RosbridgeTransport(host="localhost", port=9090)


@pytest.fixture
def mock_reactor():
    """Mock reactor that executes callFromThread calls inline."""
    r = MagicMock()
    r.callFromThread.side_effect = lambda fn, *a, **kw: fn(*a, **kw)
    return r


def _patch_connect(mock_ros):
    """Set up mock so connect() succeeds (on_ready fires immediately).

    roslibpy 2.0: on_ready callback takes zero args.
    """
    mock_ros.on_ready.side_effect = lambda cb: cb()
    mock_ros.is_connected = True


# Patch _get_reactor to return a mock reactor instead of starting Twisted
def _reactor_patch(mock_reactor_fixture=None):
    """Create a patch for _get_reactor. Used as decorator or with fixture."""
    return patch("defined_cli.transport.rosbridge._get_reactor")


class TestConnect:
    @patch("defined_cli.transport.rosbridge.roslibpy.Ros")
    @patch("defined_cli.transport.rosbridge._get_reactor")
    def test_success(self, mock_get_reactor, MockRos, transport):
        mock_reactor = MagicMock()
        mock_reactor.callFromThread.side_effect = lambda fn, *a, **kw: fn(*a, **kw)
        mock_get_reactor.return_value = mock_reactor
        _patch_connect(MockRos.return_value)
        transport.connect()
        MockRos.return_value.connect.assert_called_once()

    @patch("defined_cli.transport.rosbridge.roslibpy.Ros")
    @patch("defined_cli.transport.rosbridge._get_reactor")
    def test_raises_on_connect_exception(self, mock_get_reactor, MockRos, transport):
        mock_reactor = MagicMock()
        mock_get_reactor.return_value = mock_reactor
        mock_ros = MockRos.return_value
        mock_ros.on_ready.side_effect = lambda cb: None
        mock_reactor.callFromThread.side_effect = lambda fn, *a, **kw: (_ for _ in ()).throw(
            Exception("Connection refused")
        )
        with pytest.raises(DefinedConnectionError, match="Cannot connect"):
            transport.connect()

    @patch("defined_cli.transport.rosbridge.roslibpy.Ros")
    @patch("defined_cli.transport.rosbridge._get_reactor")
    def test_raises_when_not_connected(self, mock_get_reactor, MockRos, transport):
        mock_reactor = MagicMock()
        mock_reactor.callFromThread.side_effect = lambda fn, *a, **kw: fn(*a, **kw)
        mock_get_reactor.return_value = mock_reactor
        mock_ros = MockRos.return_value
        mock_ros.on_ready.side_effect = lambda cb: None  # never fires
        mock_ros.is_connected = False
        with pytest.raises(DefinedConnectionError, match="did not connect"):
            transport.connect()


class TestDisconnect:
    @patch("defined_cli.transport.rosbridge.roslibpy.Ros")
    @patch("defined_cli.transport.rosbridge._get_reactor")
    def test_disconnects_cleanly(self, mock_get_reactor, MockRos, transport):
        mock_reactor = MagicMock()
        mock_reactor.callFromThread.side_effect = lambda fn, *a, **kw: fn(*a, **kw)
        mock_get_reactor.return_value = mock_reactor
        _patch_connect(MockRos.return_value)
        transport.connect()
        transport.disconnect()
        MockRos.return_value.close.assert_called_once()
        assert transport._ros is None


class TestSendTask:
    @patch("defined_cli.transport.rosbridge.roslibpy.Topic")
    @patch("defined_cli.transport.rosbridge.roslibpy.Ros")
    @patch("defined_cli.transport.rosbridge._get_reactor")
    def test_publishes_to_task_command(self, mock_get_reactor, MockRos, MockTopic, transport):
        mock_reactor = MagicMock()
        mock_reactor.callFromThread.side_effect = lambda fn, *a, **kw: fn(*a, **kw)
        mock_get_reactor.return_value = mock_reactor
        mock_ros = MockRos.return_value
        _patch_connect(mock_ros)
        transport.connect()

        transport.send_task("/bt_xml/patrol.xml")
        MockTopic.assert_called_once_with(mock_ros, "/task_command", "std_msgs/String")
        MockTopic.return_value.publish.assert_called_once()

    def test_raises_when_not_connected(self, transport):
        with pytest.raises(DefinedConnectionError, match="Not connected"):
            transport.send_task("/bt_xml/patrol.xml")


class TestSubscribeStatus:
    @patch("defined_cli.transport.rosbridge.roslibpy.Topic")
    @patch("defined_cli.transport.rosbridge.roslibpy.Ros")
    @patch("defined_cli.transport.rosbridge._get_reactor")
    def test_parses_json_into_task_progress(self, mock_get_reactor, MockRos, MockTopic, transport):
        mock_reactor = MagicMock()
        mock_reactor.callFromThread.side_effect = lambda fn, *a, **kw: fn(*a, **kw)
        mock_get_reactor.return_value = mock_reactor
        _patch_connect(MockRos.return_value)
        transport.connect()

        received: list[TaskProgress] = []
        transport.subscribe_status(received.append)

        on_message = MockTopic.return_value.subscribe.call_args[0][0]
        msg = {"data": json.dumps({
            "step": "GoTo", "status": "RUNNING",
            "current": 2, "total": 5, "progress": 40,
        })}
        on_message(msg)

        assert len(received) == 1
        assert received[0] == TaskProgress(
            step="GoTo", status="RUNNING", current=2, total=5, progress=40,
        )

    @patch("defined_cli.transport.rosbridge.roslibpy.Topic")
    @patch("defined_cli.transport.rosbridge.roslibpy.Ros")
    @patch("defined_cli.transport.rosbridge._get_reactor")
    def test_skips_malformed_messages(self, mock_get_reactor, MockRos, MockTopic, transport):
        mock_reactor = MagicMock()
        mock_reactor.callFromThread.side_effect = lambda fn, *a, **kw: fn(*a, **kw)
        mock_get_reactor.return_value = mock_reactor
        _patch_connect(MockRos.return_value)
        transport.connect()

        received: list[TaskProgress] = []
        transport.subscribe_status(received.append)

        on_message = MockTopic.return_value.subscribe.call_args[0][0]
        on_message({"data": "not json"})
        assert len(received) == 0


class TestWaitReady:

    @patch("defined_cli.transport.rosbridge.roslibpy.Topic")
    @patch("defined_cli.transport.rosbridge.roslibpy.Ros")
    @patch("defined_cli.transport.rosbridge._get_reactor")
    def test_ready_when_bt_navigator_transitions_to_active(
        self, mock_get_reactor, MockRos, MockTopic, transport,
    ):
        mock_reactor = MagicMock()
        mock_reactor.callFromThread.side_effect = lambda fn, *a, **kw: fn(*a, **kw)
        mock_get_reactor.return_value = mock_reactor
        _patch_connect(MockRos.return_value)
        transport.connect()

        # Inject an ACTIVE transition when the callback subscribes
        def _fire_active(callback):
            callback({
                "transition": {"id": 3, "label": "activate"},
                "start_state": {"id": 2, "label": "inactive"},
                "goal_state": {"id": 3, "label": "active"},
            })
        MockTopic.return_value.subscribe.side_effect = _fire_active
        assert transport.wait_ready(timeout=5.0) is True

    @patch("defined_cli.transport.rosbridge.roslibpy.Topic")
    @patch("defined_cli.transport.rosbridge.roslibpy.Ros")
    @patch("defined_cli.transport.rosbridge._get_reactor")
    def test_not_ready_on_timeout(self, mock_get_reactor, MockRos, MockTopic, transport):
        mock_reactor = MagicMock()
        mock_reactor.callFromThread.side_effect = lambda fn, *a, **kw: fn(*a, **kw)
        mock_get_reactor.return_value = mock_reactor
        _patch_connect(MockRos.return_value)
        transport.connect()

        # Subscribe but never fire — timeout expected
        MockTopic.return_value.subscribe.side_effect = lambda cb: None
        assert transport.wait_ready(timeout=0.1) is False

    @patch("defined_cli.transport.rosbridge.roslibpy.Topic")
    @patch("defined_cli.transport.rosbridge.roslibpy.Ros")
    @patch("defined_cli.transport.rosbridge._get_reactor")
    def test_ignores_non_active_transitions(self, mock_get_reactor, MockRos, MockTopic, transport):
        mock_reactor = MagicMock()
        mock_reactor.callFromThread.side_effect = lambda fn, *a, **kw: fn(*a, **kw)
        mock_get_reactor.return_value = mock_reactor
        _patch_connect(MockRos.return_value)
        transport.connect()

        # Fire an inactive transition first, then active
        def _fire_both(callback):
            callback({
                "goal_state": {"id": 2, "label": "inactive"},
            })
            callback({
                "goal_state": {"id": 3, "label": "active"},
            })
        MockTopic.return_value.subscribe.side_effect = _fire_both
        assert transport.wait_ready(timeout=5.0) is True

    def test_returns_false_when_not_connected(self, transport):
        assert transport.wait_ready(timeout=1.0) is False

    @patch("defined_cli.transport.rosbridge.roslibpy.Topic")
    @patch("defined_cli.transport.rosbridge.roslibpy.Ros")
    @patch("defined_cli.transport.rosbridge._get_reactor")
    def test_unsubscribes_after_ready(self, mock_get_reactor, MockRos, MockTopic, transport):
        mock_reactor = MagicMock()
        mock_reactor.callFromThread.side_effect = lambda fn, *a, **kw: fn(*a, **kw)
        mock_get_reactor.return_value = mock_reactor
        _patch_connect(MockRos.return_value)
        transport.connect()

        def _fire_active(callback):
            callback({"goal_state": {"id": 3, "label": "active"}})
        MockTopic.return_value.subscribe.side_effect = _fire_active
        transport.wait_ready(timeout=5.0)
        MockTopic.return_value.unsubscribe.assert_called_once()


class TestPublishVelocity:

    def test_noop_when_not_connected(self, transport):
        # Should not raise even when disconnected
        transport.publish_velocity(0.2, 0.5)

    @patch("defined_cli.transport.rosbridge.roslibpy.Topic")
    @patch("defined_cli.transport.rosbridge.roslibpy.Ros")
    @patch("defined_cli.transport.rosbridge._get_reactor")
    def test_publishes_to_cmd_vel_topic(self, mock_get_reactor, MockRos, MockTopic, transport):
        mock_reactor = MagicMock()
        mock_reactor.callFromThread.side_effect = lambda fn, *a, **kw: fn(*a, **kw)
        mock_get_reactor.return_value = mock_reactor
        _patch_connect(MockRos.return_value)
        transport.connect()

        transport.publish_velocity(0.2, 0.5)

        MockTopic.assert_called_with(MockRos.return_value, "/cmd_vel", "geometry_msgs/Twist")
        MockTopic.return_value.publish.assert_called_once()

    @patch("defined_cli.transport.rosbridge.roslibpy.Topic")
    @patch("defined_cli.transport.rosbridge.roslibpy.Ros")
    @patch("defined_cli.transport.rosbridge._get_reactor")
    def test_message_has_correct_linear_and_angular(self, mock_get_reactor, MockRos, MockTopic, transport):
        mock_reactor = MagicMock()
        mock_reactor.callFromThread.side_effect = lambda fn, *a, **kw: fn(*a, **kw)
        mock_get_reactor.return_value = mock_reactor
        _patch_connect(MockRos.return_value)
        transport.connect()

        transport.publish_velocity(0.2, -0.5)

        _, call_args, _ = MockTopic.return_value.publish.mock_calls[0]
        msg = call_args[0]
        assert msg.data["linear"]["x"] == pytest.approx(0.2)
        assert msg.data["linear"]["y"] == pytest.approx(0.0)
        assert msg.data["linear"]["z"] == pytest.approx(0.0)
        assert msg.data["angular"]["z"] == pytest.approx(-0.5)

    @patch("defined_cli.transport.rosbridge.roslibpy.Topic")
    @patch("defined_cli.transport.rosbridge.roslibpy.Ros")
    @patch("defined_cli.transport.rosbridge._get_reactor")
    def test_zero_velocity_is_valid(self, mock_get_reactor, MockRos, MockTopic, transport):
        mock_reactor = MagicMock()
        mock_reactor.callFromThread.side_effect = lambda fn, *a, **kw: fn(*a, **kw)
        mock_get_reactor.return_value = mock_reactor
        _patch_connect(MockRos.return_value)
        transport.connect()

        transport.publish_velocity(0.0, 0.0)
        MockTopic.return_value.publish.assert_called_once()


# ---------------------------------------------------------------------------
# check_readiness
# ---------------------------------------------------------------------------

from defined_cli.transport.readiness import ReadinessReport, TopicCheck, TopicResult


class TestCheckReadinessBase:
    def test_default_returns_not_connected(self):
        from defined_cli.transport import TransportBase

        class _StubTransport(TransportBase):
            def connect(self): ...
            def disconnect(self): ...
            def send_task(self, bt_xml_path): ...
            def subscribe_status(self, callback): ...
            def wait_ready(self, timeout=10.0): return True

        base = _StubTransport()
        report = base.check_readiness([])
        assert report.connected is False
        assert report.topics == []


class TestCheckReadinessRosbridge:

    @patch("defined_cli.transport.rosbridge.roslibpy.Topic")
    @patch("defined_cli.transport.rosbridge.roslibpy.Ros")
    @patch("defined_cli.transport.rosbridge._get_reactor")
    def test_healthy_topic_returns_publishing(self, mock_get_reactor, MockRos, MockTopic, transport):
        mock_reactor = MagicMock()
        mock_reactor.callFromThread.side_effect = lambda fn, *a, **kw: fn(*a, **kw)
        mock_get_reactor.return_value = mock_reactor
        _patch_connect(MockRos.return_value)
        transport.connect()

        def _fire_message(callback):
            callback({"data": "hello"})
        MockTopic.return_value.subscribe.side_effect = _fire_message

        checks = [TopicCheck(topic="/rosout", msg_type="rcl_interfaces/Log", timeout=1.0)]
        report = transport.check_readiness(checks)

        assert report.connected is True
        assert len(report.topics) == 1
        assert report.topics[0].publishing is True
        assert report.topics[0].latency_ms is not None

    @patch("defined_cli.transport.rosbridge.roslibpy.Topic")
    @patch("defined_cli.transport.rosbridge.roslibpy.Ros")
    @patch("defined_cli.transport.rosbridge._get_reactor")
    def test_timeout_topic_returns_not_publishing(self, mock_get_reactor, MockRos, MockTopic, transport):
        mock_reactor = MagicMock()
        mock_reactor.callFromThread.side_effect = lambda fn, *a, **kw: fn(*a, **kw)
        mock_get_reactor.return_value = mock_reactor
        _patch_connect(MockRos.return_value)
        transport.connect()

        MockTopic.return_value.subscribe.side_effect = lambda cb: None

        checks = [TopicCheck(topic="/map", msg_type="nav_msgs/OccupancyGrid", timeout=0.1)]
        report = transport.check_readiness(checks)

        assert report.connected is True
        assert len(report.topics) == 1
        assert report.topics[0].publishing is False
        assert report.topics[0].error is not None

    def test_returns_not_connected_when_disconnected(self, transport):
        checks = [TopicCheck(topic="/odom", msg_type="nav_msgs/Odometry")]
        report = transport.check_readiness(checks)
        assert report.connected is False

    @patch("defined_cli.transport.rosbridge.roslibpy.Topic")
    @patch("defined_cli.transport.rosbridge.roslibpy.Ros")
    @patch("defined_cli.transport.rosbridge._get_reactor")
    def test_unsubscribes_after_check(self, mock_get_reactor, MockRos, MockTopic, transport):
        mock_reactor = MagicMock()
        mock_reactor.callFromThread.side_effect = lambda fn, *a, **kw: fn(*a, **kw)
        mock_get_reactor.return_value = mock_reactor
        _patch_connect(MockRos.return_value)
        transport.connect()

        MockTopic.return_value.subscribe.side_effect = lambda cb: cb({"data": "ok"})

        checks = [TopicCheck(topic="/rosout", msg_type="rcl_interfaces/Log", timeout=1.0)]
        transport.check_readiness(checks)

        MockTopic.return_value.unsubscribe.assert_called()
