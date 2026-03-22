"""RosbridgeTransport — WebSocket connection to rosbridge_server."""

from __future__ import annotations

import json
from collections.abc import Callable

import roslibpy

from defined_cli.errors import ConnectionError as DefinedConnectionError
from defined_cli.transport import TaskProgress, TransportBase


class RosbridgeTransport(TransportBase):
    """Transport that talks to a rosbridge WebSocket server.

    Args:
        host: rosbridge hostname.
        port: rosbridge WebSocket port.
    """

    def __init__(self, host: str = "localhost", port: int = 9090) -> None:
        self._host = host
        self._port = port
        self._ros: roslibpy.Ros | None = None
        self._status_topic: roslibpy.Topic | None = None

    def connect(self) -> None:
        self._ros = roslibpy.Ros(host=self._host, port=self._port)
        try:
            self._ros.run()
        except Exception as exc:
            raise DefinedConnectionError(
                f"Cannot connect to rosbridge at ws://{self._host}:{self._port}",
                suggestion="Is the simulation running? Try: defined status",
                detail=str(exc),
            ) from exc
        if not self._ros.is_connected:
            raise DefinedConnectionError(
                f"rosbridge at ws://{self._host}:{self._port} did not connect",
                suggestion="Check that rosbridge_server is running in the container",
            )

    def disconnect(self) -> None:
        if self._status_topic is not None:
            self._status_topic.unsubscribe()
            self._status_topic = None
        if self._ros is not None:
            self._ros.terminate()
            self._ros = None

    def send_task(self, bt_xml_path: str) -> None:
        if self._ros is None or not self._ros.is_connected:
            raise DefinedConnectionError(
                "Not connected to rosbridge",
                suggestion="Call connect() first",
            )
        topic = roslibpy.Topic(self._ros, "/task_command", "std_msgs/String")
        topic.publish(roslibpy.Message({"data": bt_xml_path}))

    def subscribe_status(self, callback: Callable[[TaskProgress], None]) -> None:
        if self._ros is None or not self._ros.is_connected:
            raise DefinedConnectionError(
                "Not connected to rosbridge",
                suggestion="Call connect() first",
            )
        self._status_topic = roslibpy.Topic(
            self._ros, "/task_status", "std_msgs/String",
        )

        def _on_message(msg: dict) -> None:
            try:
                data = json.loads(msg["data"])
                progress = TaskProgress(
                    step=data["step"],
                    status=data["status"],
                    current=data["current"],
                    total=data["total"],
                    progress=data["progress"],
                )
                callback(progress)
            except (json.JSONDecodeError, KeyError):
                pass  # skip malformed messages

        self._status_topic.subscribe(_on_message)
