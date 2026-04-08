"""Pose fetch helper — grab robot position via rosbridge.

One-shot connection: connect, subscribe, get one message, disconnect.
Reused by ``defined world mark`` and ``defined world watch``.

This module has zero CLI-specific imports (no click, no rich).
"""

from __future__ import annotations

import threading

import roslibpy

from defined_cli.transport.rosbridge import _get_reactor


def fetch_robot_pose(
    host: str = "localhost",
    port: int = 9090,
    timeout: float = 5.0,
    topic: str = "/amcl_pose",
) -> tuple[float, float]:
    """Fetch the robot's current (x, y) position.

    Connects to rosbridge, subscribes to the pose topic, waits for
    one message, extracts (x, y), and disconnects.

    Args:
        host: rosbridge hostname.
        port: rosbridge WebSocket port.
        timeout: Seconds to wait for a pose message.
        topic: ROS2 topic to subscribe to. Default ``/amcl_pose``
            (``geometry_msgs/PoseWithCovarianceStamped``).

    Returns:
        Tuple of (x, y) in the map frame.

    Raises:
        TimeoutError: If no pose message is received within ``timeout``.
        ConnectionError: If rosbridge connection fails.
    """
    reactor = _get_reactor()
    ros = roslibpy.Ros(host=host, port=port)

    ready = threading.Event()
    ros.on_ready(ready.set)
    reactor.callFromThread(ros.connect)

    if not ready.wait(timeout=timeout):
        raise ConnectionError(f"Cannot connect to rosbridge at ws://{host}:{port}")

    result: dict = {}
    got_pose = threading.Event()

    def _on_message(msg: dict) -> None:
        try:
            # Support both PoseWithCovarianceStamped and PoseStamped
            if "pose" in msg and "pose" in msg["pose"]:
                pos = msg["pose"]["pose"]["position"]
            elif "pose" in msg and "position" in msg["pose"]:
                pos = msg["pose"]["position"]
            else:
                pos = msg.get("position", msg)
            result["x"] = pos["x"]
            result["y"] = pos["y"]
            got_pose.set()
        except (KeyError, TypeError):
            pass

    pose_topic = roslibpy.Topic(ros, topic, "geometry_msgs/PoseWithCovarianceStamped")
    reactor.callFromThread(pose_topic.subscribe, _on_message)

    if not got_pose.wait(timeout=timeout):
        try:
            reactor.callFromThread(pose_topic.unsubscribe)
            ros.close()
        except Exception:
            pass
        raise TimeoutError(
            f"No pose received on {topic} within {timeout}s. "
            "Is SLAM/AMCL running?"
        )

    try:
        reactor.callFromThread(pose_topic.unsubscribe)
        ros.close()
    except Exception:
        pass

    return result["x"], result["y"]


def subscribe_clicked_point(
    host: str = "localhost",
    port: int = 9090,
    callback: callable = None,
) -> tuple[roslibpy.Ros, roslibpy.Topic]:
    """Subscribe to /clicked_point for interactive POI marking.

    Returns the (ros, topic) handles so the caller can manage the
    subscription lifetime (unsubscribe + close on KeyboardInterrupt).

    Args:
        host: rosbridge hostname.
        port: rosbridge WebSocket port.
        callback: Called with (x, y) for each click.

    Returns:
        Tuple of (ros_client, topic) for cleanup.
    """
    reactor = _get_reactor()
    ros = roslibpy.Ros(host=host, port=port)

    ready = threading.Event()
    ros.on_ready(ready.set)
    reactor.callFromThread(ros.connect)

    if not ready.wait(timeout=10.0):
        raise ConnectionError(f"Cannot connect to rosbridge at ws://{host}:{port}")

    def _on_click(msg: dict) -> None:
        try:
            point = msg["point"]
            if callback:
                callback(point["x"], point["y"])
        except (KeyError, TypeError):
            pass

    topic = roslibpy.Topic(ros, "/clicked_point", "geometry_msgs/PointStamped")
    reactor.callFromThread(topic.subscribe, _on_click)

    return ros, topic
