"""Tests for RosbridgeTransport — WebSocket communication via roslibpy."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from defined_cli.errors import ConnectionError as DefinedConnectionError
from defined_cli.transport import TaskProgress
from defined_cli.transport.rosbridge import RosbridgeTransport


@pytest.fixture
def transport() -> RosbridgeTransport:
    return RosbridgeTransport(host="localhost", port=9090)


class TestConnect:
    @patch("defined_cli.transport.rosbridge.roslibpy.Ros")
    def test_success(self, MockRos, transport: RosbridgeTransport) -> None:
        mock_ros = MockRos.return_value
        mock_ros.is_connected = True
        transport.connect()
        mock_ros.run.assert_called_once()

    @patch("defined_cli.transport.rosbridge.roslibpy.Ros")
    def test_raises_on_run_exception(self, MockRos, transport: RosbridgeTransport) -> None:
        mock_ros = MockRos.return_value
        mock_ros.run.side_effect = Exception("Connection refused")
        with pytest.raises(DefinedConnectionError, match="Cannot connect"):
            transport.connect()

    @patch("defined_cli.transport.rosbridge.roslibpy.Ros")
    def test_raises_when_not_connected(self, MockRos, transport: RosbridgeTransport) -> None:
        mock_ros = MockRos.return_value
        mock_ros.is_connected = False
        with pytest.raises(DefinedConnectionError, match="did not connect"):
            transport.connect()


class TestDisconnect:
    @patch("defined_cli.transport.rosbridge.roslibpy.Ros")
    def test_terminates_cleanly(self, MockRos, transport: RosbridgeTransport) -> None:
        mock_ros = MockRos.return_value
        mock_ros.is_connected = True
        transport.connect()
        transport.disconnect()
        mock_ros.terminate.assert_called_once()
        assert transport._ros is None


class TestSendTask:
    @patch("defined_cli.transport.rosbridge.roslibpy.Topic")
    @patch("defined_cli.transport.rosbridge.roslibpy.Ros")
    def test_publishes_to_task_command(self, MockRos, MockTopic, transport: RosbridgeTransport) -> None:
        mock_ros = MockRos.return_value
        mock_ros.is_connected = True
        transport.connect()

        transport.send_task("/bt_xml/patrol.xml")
        MockTopic.assert_called_once_with(mock_ros, "/task_command", "std_msgs/String")
        MockTopic.return_value.publish.assert_called_once()

    def test_raises_when_not_connected(self, transport: RosbridgeTransport) -> None:
        with pytest.raises(DefinedConnectionError, match="Not connected"):
            transport.send_task("/bt_xml/patrol.xml")


class TestSubscribeStatus:
    @patch("defined_cli.transport.rosbridge.roslibpy.Topic")
    @patch("defined_cli.transport.rosbridge.roslibpy.Ros")
    def test_parses_json_into_task_progress(self, MockRos, MockTopic, transport: RosbridgeTransport) -> None:
        mock_ros = MockRos.return_value
        mock_ros.is_connected = True
        transport.connect()

        received: list[TaskProgress] = []
        transport.subscribe_status(received.append)

        # Simulate a message arriving
        subscribe_call = MockTopic.return_value.subscribe
        subscribe_call.assert_called_once()
        on_message = subscribe_call.call_args[0][0]

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
    def test_skips_malformed_messages(self, MockRos, MockTopic, transport: RosbridgeTransport) -> None:
        mock_ros = MockRos.return_value
        mock_ros.is_connected = True
        transport.connect()

        received: list[TaskProgress] = []
        transport.subscribe_status(received.append)

        on_message = MockTopic.return_value.subscribe.call_args[0][0]
        on_message({"data": "not json"})
        assert len(received) == 0
