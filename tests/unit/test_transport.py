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
    @patch("defined_cli.transport.rosbridge.roslibpy.Ros")
    @patch("defined_cli.transport.rosbridge._get_reactor")
    def test_ready_when_nav2_topics_present(self, mock_get_reactor, MockRos, transport):
        mock_reactor = MagicMock()
        mock_reactor.callFromThread.side_effect = lambda fn, *a, **kw: fn(*a, **kw)
        mock_get_reactor.return_value = mock_reactor
        mock_ros = MockRos.return_value
        _patch_connect(mock_ros)
        mock_ros.get_topics.return_value = [
            "/cmd_vel", "/odom", "/bt_navigator/transition_event"
        ]
        transport.connect()
        assert transport.wait_ready(timeout=5.0) is True

    @patch("defined_cli.transport.rosbridge.roslibpy.Ros")
    @patch("defined_cli.transport.rosbridge._get_reactor")
    def test_not_ready_when_no_nav2_topics(self, mock_get_reactor, MockRos, transport):
        mock_reactor = MagicMock()
        mock_reactor.callFromThread.side_effect = lambda fn, *a, **kw: fn(*a, **kw)
        mock_get_reactor.return_value = mock_reactor
        mock_ros = MockRos.return_value
        _patch_connect(mock_ros)
        mock_ros.get_topics.return_value = ["/cmd_vel", "/odom"]
        transport.connect()
        assert transport.wait_ready(timeout=0.1) is False

    @patch("defined_cli.transport.rosbridge.roslibpy.Ros")
    @patch("defined_cli.transport.rosbridge._get_reactor")
    def test_returns_false_on_error(self, mock_get_reactor, MockRos, transport):
        mock_reactor = MagicMock()
        mock_reactor.callFromThread.side_effect = lambda fn, *a, **kw: fn(*a, **kw)
        mock_get_reactor.return_value = mock_reactor
        mock_ros = MockRos.return_value
        _patch_connect(mock_ros)
        mock_ros.get_topics.side_effect = Exception("connection lost")
        transport.connect()
        assert transport.wait_ready(timeout=0.1) is False

    def test_returns_false_when_not_connected(self, transport):
        assert transport.wait_ready(timeout=1.0) is False
