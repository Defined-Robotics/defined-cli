"""RosbridgeTransport — WebSocket connection to rosbridge_server.

roslibpy uses the Twisted event loop internally. Twisted is a Python
async networking framework that runs its own thread-based reactor. All
roslibpy publish/subscribe calls **must** be dispatched via
``reactor.callFromThread()``; calling them directly from a non-Twisted
thread causes silent failures or data corruption.

Cleanup exceptions during disconnect are logged at DEBUG level rather
than silently swallowed — helps diagnose transport teardown issues.

``_get_reactor()`` starts the Twisted reactor in a daemon thread once
per process and returns it. All methods in this module use it as the
single dispatch point.

Transport boundary note
-----------------------
``fetch_pose()`` and the helper functions in ``transport/pose.py`` overlap:
``pose.py`` opens a one-shot connection (connect → get one message → close),
while ``fetch_pose()`` here reuses the existing persistent connection.
``pose.py`` is still used by the standalone CLI commands (``defined world
mark/watch``) that run without a live session. Both modules share the same
underlying rosbridge protocol.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from collections.abc import Callable

import roslibpy

_log = logging.getLogger(__name__)

from defined_cli.errors import TransportConnectionError as DefinedConnectionError
from defined_cli.transport import TaskProgress, TransportBase

# ---------------------------------------------------------------------------
# Twisted reactor — one per process
# ---------------------------------------------------------------------------

# roslibpy drives its WebSocket I/O through the Twisted event loop (reactor).
# The reactor must run in a dedicated thread; once started it cannot be
# stopped and restarted. We hold a module-level reference so all
# RosbridgeTransport instances share the same running reactor.
_reactor_lock = threading.Lock()
_reactor_ref: object | None = None


def _get_reactor() -> object:
    """Start the Twisted reactor thread once and return it.

    Blocks until the reactor event loop is actually running so that
    subsequent ``callFromThread`` calls are guaranteed to be processed.
    """
    global _reactor_ref
    with _reactor_lock:
        if _reactor_ref is not None:
            return _reactor_ref
        from twisted.internet import reactor

        thread = threading.Thread(target=reactor.run, args=(False,), daemon=True)
        thread.start()
        # Wait until the event loop is actually processing callbacks.
        # Polling reactor.running avoids a callWhenRunning race and keeps
        # the lock-hold time minimal.
        deadline = time.monotonic() + 5.0
        while not reactor.running and time.monotonic() < deadline:
            time.sleep(0.01)
        _reactor_ref = reactor
        return reactor


# ---------------------------------------------------------------------------
# RosbridgeTransport
# ---------------------------------------------------------------------------


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

    @property
    def is_connected(self) -> bool:
        """True if the WebSocket connection is active."""
        return self._ros is not None and self._ros.is_connected

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
                _log.debug("Failed to unsubscribe status topic", exc_info=True)
            self._status_topic = None
        if self._ros is not None:
            try:
                if self._ros.is_connected:
                    self._ros.close()
            except Exception:
                _log.debug("Failed to close rosbridge connection", exc_info=True)
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

    def cancel_task(self) -> None:
        """Halt the running BT tree by publishing ``"STOP"`` to /task_command.

        The executor calls ``haltTree()`` on receipt, which propagates
        ``onHalted()`` to every running node (cancels Nav2 goals,
        stops explore_lite via resume=false, etc.).
        No-op when not connected.
        """
        if self._ros is None or not self._ros.is_connected:
            return
        topic = roslibpy.Topic(self._ros, "/task_command", "std_msgs/String")
        self._reactor.callFromThread(
            topic.publish, roslibpy.Message({"data": "STOP"}),
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
                _log.debug("Malformed status message, skipping", exc_info=True)

        self._reactor.callFromThread(self._status_topic.subscribe, _on_message)

    def subscribe_reports(self, callback: Callable[[str], None]) -> None:
        if self._ros is None or not self._ros.is_connected:
            return
        self._reports_topic = roslibpy.Topic(
            self._ros, "/task_reports", "std_msgs/String",
        )

        def _on_report(msg: dict) -> None:
            data = msg.get("data", "")
            if data:
                callback(data)

        self._reactor.callFromThread(self._reports_topic.subscribe, _on_report)

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
                _log.debug("Malformed executor status message", exc_info=True)

        self._reactor.callFromThread(topic.subscribe, _on_idle)
        result = ready.wait(timeout=timeout)
        try:
            self._reactor.callFromThread(topic.unsubscribe)
        except Exception:
            _log.debug("Failed to unsubscribe executor topic", exc_info=True)
        return result

    def fetch_pose(self, timeout: float = 5.0, topic: str = "/odom") -> tuple[float, float]:
        """Fetch robot (x, y) using the existing rosbridge connection.

        Default topic is ``/odom`` (nav_msgs/Odometry) which is always
        published by the diff_drive controller. Also supports
        ``/amcl_pose`` (PoseWithCovarianceStamped) and other pose topics.
        """
        if self._ros is None or not self._ros.is_connected:
            raise ConnectionError("Not connected to rosbridge")

        result: dict = {}
        got_pose = threading.Event()

        def _on_message(msg: dict) -> None:
            try:
                # nav_msgs/Odometry: msg.pose.pose.position
                if "pose" in msg and "pose" in msg["pose"]:
                    pos = msg["pose"]["pose"]["position"]
                # geometry_msgs/PoseStamped: msg.pose.position
                elif "pose" in msg and "position" in msg["pose"]:
                    pos = msg["pose"]["position"]
                else:
                    pos = msg.get("position", msg)
                result["x"] = pos["x"]
                result["y"] = pos["y"]
                got_pose.set()
            except (KeyError, TypeError):
                _log.debug("Unexpected pose message format", exc_info=True)

        msg_type = {
            "/odom": "nav_msgs/Odometry",
            "/amcl_pose": "geometry_msgs/PoseWithCovarianceStamped",
        }.get(topic, "nav_msgs/Odometry")
        pose_topic = roslibpy.Topic(self._ros, topic, msg_type)
        self._reactor.callFromThread(pose_topic.subscribe, _on_message)

        if not got_pose.wait(timeout=timeout):
            try:
                self._reactor.callFromThread(pose_topic.unsubscribe)
            except Exception:
                _log.debug("Failed to unsubscribe pose topic after timeout", exc_info=True)
            raise TimeoutError(
                f"No pose received on {topic} within {timeout}s. Is SLAM/AMCL running?"
            )

        try:
            self._reactor.callFromThread(pose_topic.unsubscribe)
        except Exception:
            _log.debug("Failed to unsubscribe pose topic", exc_info=True)

        return result["x"], result["y"]

    def publish_velocity(self, linear_x: float, angular_z: float) -> None:
        if self._ros is None or not self._ros.is_connected:
            return
        topic = roslibpy.Topic(self._ros, "/cmd_vel", "geometry_msgs/Twist")
        self._reactor.callFromThread(
            topic.publish,
            roslibpy.Message({
                "linear": {"x": float(linear_x), "y": 0.0, "z": 0.0},
                "angular": {"x": 0.0, "y": 0.0, "z": float(angular_z)},
            }),
        )

    def wait_ready(self, timeout: float = 60.0) -> bool:
        """Wait for Nav2 bt_navigator to reach ACTIVE lifecycle state.

        Subscribes to ``/bt_navigator/transition_event`` and waits for a
        lifecycle transition whose ``goal_state`` is ACTIVE (id=3).
        Returns True when the navigator is active, False on timeout.
        Non-fatal — the task may still work for non-nav verbs.

        Args:
            timeout: Seconds to wait before giving up.

        Returns:
            True if bt_navigator reached ACTIVE within *timeout*.
        """
        if self._ros is None or not self._ros.is_connected:
            return False

        ready = threading.Event()
        topic = roslibpy.Topic(
            self._ros,
            "/bt_navigator/transition_event",
            "lifecycle_msgs/TransitionEvent",
        )

        def _on_transition(msg: dict) -> None:
            try:
                goal = msg.get("goal_state", {})
                # lifecycle_msgs ACTIVE state id is 3
                if goal.get("id") == 3 or goal.get("label") == "active":
                    ready.set()
            except (KeyError, TypeError, AttributeError):
                _log.debug("Unexpected transition event format", exc_info=True)

        self._reactor.callFromThread(topic.subscribe, _on_transition)
        result = ready.wait(timeout=timeout)
        try:
            self._reactor.callFromThread(topic.unsubscribe)
        except Exception:
            _log.debug("Failed to unsubscribe transition topic", exc_info=True)
        return result
