"""RosbridgeTransport — WebSocket connection to rosbridge_server."""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable

import roslibpy

from defined_cli.errors import ConnectionError as DefinedConnectionError
from defined_cli.transport import TaskProgress, TransportBase

# roslibpy uses a global Twisted reactor. We start it once and reuse it.
_reactor_lock = threading.Lock()
_reactor_ref: object | None = None  # holds the Twisted reactor once started


def _get_reactor() -> object:
    """Start the Twisted reactor thread once and return it."""
    global _reactor_ref
    with _reactor_lock:
        if _reactor_ref is not None:
            return _reactor_ref
        from twisted.internet import reactor

        thread = threading.Thread(target=reactor.run, args=(False,), daemon=True)
        thread.start()
        _reactor_ref = reactor
        return reactor


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
        self._reactor: object | None = None
        self._status_topic: roslibpy.Topic | None = None

    def connect(self) -> None:
        self._reactor = reactor = _get_reactor()
        self._ros = roslibpy.Ros(host=self._host, port=self._port)
        ready = threading.Event()
        # roslibpy 2.0: on_ready callback takes zero args
        self._ros.on_ready(ready.set)
        try:
            # connect() must be called from the reactor thread
            reactor.callFromThread(self._ros.connect)
            if not ready.wait(timeout=10.0):
                raise DefinedConnectionError(
                    f"rosbridge at ws://{self._host}:{self._port} did not connect",
                    suggestion="Check that rosbridge_server is running in the container",
                )
        except DefinedConnectionError:
            raise
        except Exception as exc:
            raise DefinedConnectionError(
                f"Cannot connect to rosbridge at ws://{self._host}:{self._port}",
                suggestion="Is the simulation running? Try: defined status",
                detail=str(exc),
            ) from exc

    def disconnect(self) -> None:
        if self._status_topic is not None:
            try:
                self._status_topic.unsubscribe()
            except Exception:
                pass
            self._status_topic = None
        if self._ros is not None:
            try:
                if self._ros.is_connected:
                    self._ros.close()
            except Exception:
                pass
            self._ros = None

    def send_task(self, bt_xml_path: str) -> None:
        if self._ros is None or not self._ros.is_connected:
            raise DefinedConnectionError(
                "Not connected to rosbridge",
                suggestion="Call connect() first",
            )
        topic = roslibpy.Topic(self._ros, "/task_command", "std_msgs/String")
        self._reactor.callFromThread(
            topic.publish, roslibpy.Message({"data": bt_xml_path}),
        )

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

        self._reactor.callFromThread(self._status_topic.subscribe, _on_message)

    def wait_for_executor(self, timeout: float = 60.0) -> bool:
        """Wait for the BT executor to publish an IDLE heartbeat on /task_status."""
        if self._ros is None or not self._ros.is_connected:
            return False

        ready = threading.Event()
        topic = roslibpy.Topic(self._ros, "/task_status", "std_msgs/String")

        def _on_idle(msg: dict) -> None:
            try:
                data = json.loads(msg["data"])
                if data.get("status") == "IDLE":
                    ready.set()
            except (json.JSONDecodeError, KeyError):
                pass

        self._reactor.callFromThread(topic.subscribe, _on_idle)
        result = ready.wait(timeout=timeout)
        try:
            self._reactor.callFromThread(topic.unsubscribe)
        except Exception:
            pass
        return result

    def wait_ready(self, timeout: float = 60.0) -> bool:
        """Wait for Nav2 to be ready by checking for the navigate_to_pose action topics.

        Polls the rosbridge topic list for '/navigate_to_pose/_action/status'
        which indicates the action server is up. Returns True when found,
        False on timeout. Non-fatal — the task may still work for non-nav verbs.
        """
        if self._ros is None or not self._ros.is_connected:
            return False

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                topics = self._ros.get_topics()
                topic_names = [t["name"] if isinstance(t, dict) else t for t in topics]
                if any("/bt_navigator" in t for t in topic_names):
                    return True
            except Exception:
                pass
            time.sleep(2.0)
        return False
