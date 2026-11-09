"""ROS 2 node: the security robot's state machine, the only /cmd_vel publisher.

Follows docs/interfaces.md (contract v0.3). The logic is in machine.py; this
node only turns messages into calls and the returned (topic, data) pairs
back into messages.
"""

import json
import signal
import time
from dataclasses import fields

import rclpy
from geometry_msgs.msg import Twist
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile
from rclpy.signals import SignalHandlerOptions
from std_msgs.msg import Bool, Empty, Int32, String

from .machine import Settings, StateMachine

# Latched: camera_tilt gets the last angle even if it starts after us
TILT_QOS = QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL)

EMPTY_TOPICS = ("/avoidance/start", "/avoidance/cancel",
                "/password/start", "/password/cancel")
STRING_TOPICS = ("/robot/state", "/audio/play", "/detect/request",
                 "/telegram/alert", "/telegram/blocking")


class StateMachineNode(Node):
    def __init__(self):
        super().__init__("state_machine")
        settings = Settings()
        for f in fields(Settings):
            setattr(settings, f.name,
                    float(self.declare_parameter(f.name, f.default).value))
        rate = float(self.declare_parameter("tick_rate", 10.0).value)

        self.machine = StateMachine(settings, self.now())
        self.pubs = {"/cmd_vel": self.create_publisher(Twist, "/cmd_vel", 10),
                     "/camera/tilt": self.create_publisher(Int32, "/camera/tilt", TILT_QOS)}
        for topic in EMPTY_TOPICS:
            self.pubs[topic] = self.create_publisher(Empty, topic, 10)
        for topic in STRING_TOPICS:
            self.pubs[topic] = self.create_publisher(String, topic, 10)

        m = self.machine
        self.create_subscription(String, "/gesture/command",
                                 lambda msg: self.run(m.on_gesture, msg.data), 10)
        self.create_subscription(Bool, "/obstacle/detected",
                                 lambda msg: self.run(m.on_obstacle, msg.data), 10)
        self.create_subscription(
            Twist, "/avoidance/cmd_vel",
            lambda msg: self.run(m.on_avoidance_cmd, msg.linear.x, msg.angular.z), 10)
        self.create_subscription(String, "/avoidance/result",
                                 lambda msg: self.run(m.on_avoidance_result, msg.data), 10)
        self.create_subscription(String, "/password/result",
                                 lambda msg: self.run(m.on_password_result, msg.data), 10)
        self.create_subscription(String, "/detect/result",
                                 lambda msg: self.run_json(m.on_detect_result, msg), 10)
        self.create_subscription(String, "/telegram/decision",
                                 lambda msg: self.run_json(m.on_telegram_decision, msg), 10)

        self.create_timer(1.0 / rate, lambda: self.run(m.tick))
        self.create_timer(1.0, self.publish_state)  # 1 Hz, on top of every change
        # The camera may have been left up: start level (D31)
        m.tilt = int(settings.tilt_level)
        self.publish([("/camera/tilt", m.tilt)])
        self.get_logger().info("state_machine ready in %s" % m.state)

    def now(self):
        return self.get_clock().now().nanoseconds * 1e-9

    def run(self, handler, *args):
        self.publish(handler(*args, self.now()))

    def run_json(self, handler, msg):
        try:
            reply = json.loads(msg.data)
        except ValueError:
            self.get_logger().warning("bad JSON ignored: %r" % msg.data)
            return
        if isinstance(reply, dict):
            self.run(handler, reply)

    def publish(self, out):
        for topic, data in out:
            if topic == "/cmd_vel":
                msg = Twist()
                msg.linear.x, msg.angular.z = data
            elif topic == "/camera/tilt":
                msg = Int32(data=data)
            elif topic in EMPTY_TOPICS:
                msg = Empty()
            else:
                msg = String(data=data)
                if topic == "/robot/state":
                    self.get_logger().info("-> %s" % data)
            self.pubs[topic].publish(msg)

    def publish_state(self):
        self.pubs["/robot/state"].publish(String(data=self.machine.state))


def main(args=None):
    # Python handles Ctrl-C, so the context is still valid for the final stop.
    rclpy.init(args=args, signal_handler_options=SignalHandlerOptions.NO)
    # SIGTERM (launch escalating, docker stop) also ends in the final stop below.
    signal.signal(signal.SIGTERM, signal.default_int_handler)
    node = StateMachineNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        # Ctrl-C arrives twice (the process group's and launch's): the second
        # must not cut the stop short.
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        # Leave the wheels stopped. Three times, as in #42: one publish right
        # before destroy_node can be lost.
        for _ in range(3):
            node.pubs["/cmd_vel"].publish(Twist())
            time.sleep(0.05)
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
