"""ROS 2 node: gesture-sequence password check for the security checkpoint.

Topics (all std_msgs, so no custom message package is needed):
  sub  /password/start   Empty   begin a session (main state machine, person seen)
  sub  /password/cancel  Empty   abort the session (e.g. person walked away)
  sub  /password/token   String  inject an already-accepted token (sim / testing)
  sub  <image_topic>     Image   camera frames, input_mode == "camera"
  sub  <fingers_topic>   Int32   raw per-frame finger count (-1 = no hand),
                                 input_mode == "fingers_topic"
  pub  /password/result  String  "granted" | "denied" | "cancelled"  (once per session)
  pub  /password/event   String  JSON progress events for audio / UI
"""

import json

import rclpy
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from std_msgs.msg import Empty, Int32, String

from .gesture_input import GestureDebouncer
from .verifier import EventType, PasswordVerifier

RESULT_FOR_EVENT = {
    EventType.GRANTED: "granted",
    EventType.LOCKED_OUT: "denied",
    EventType.CANCELLED: "cancelled",
}


class PasswordNode(Node):
    def __init__(self):
        super().__init__("password_node")
        p = self.declare_parameter
        p("password_hash", "")
        p("salt", "")
        p("password_length", 4)
        p("max_attempts", 3)
        p("input_timeout", 15.0)
        p("hold_time", 0.8)
        p("release_time", 0.4)
        p("input_mode", "camera")  # camera | fingers_topic | topic_only
        p("image_topic", "/camera/image_raw")
        p("fingers_topic", "/gesture/fingers")
        p("process_every_n_frames", 1)
        p("min_detection_confidence", 0.6)

        g = lambda name: self.get_parameter(name).value
        if not g("password_hash") or not g("salt"):
            raise RuntimeError("password_hash and salt must be set (see make_password_hash)")

        self.verifier = PasswordVerifier(
            password_hash=g("password_hash"),
            salt=g("salt"),
            password_length=int(g("password_length")),
            max_attempts=int(g("max_attempts")),
            input_timeout=float(g("input_timeout")),
        )
        self.debouncer = GestureDebouncer(
            hold_time=float(g("hold_time")),
            release_time=float(g("release_time")),
        )

        self.result_pub = self.create_publisher(String, "/password/result", 10)
        self.event_pub = self.create_publisher(String, "/password/event", 10)
        self.create_subscription(Empty, "/password/start", self.on_start, 10)
        self.create_subscription(Empty, "/password/cancel", self.on_cancel, 10)
        self.create_subscription(String, "/password/token", self.on_token, 10)

        self.mode = g("input_mode")
        self.every_n = max(1, int(g("process_every_n_frames")))
        self._frame_i = 0
        self.counter = None
        if self.mode == "camera":
            from cv_bridge import CvBridge
            from sensor_msgs.msg import Image
            from .finger_counter import HandFingerCounter
            self.bridge = CvBridge()
            self.counter = HandFingerCounter(float(g("min_detection_confidence")))
            self.create_subscription(Image, g("image_topic"), self.on_image,
                                     qos_profile_sensor_data)
        elif self.mode == "fingers_topic":
            self.create_subscription(Int32, g("fingers_topic"), self.on_fingers, 10)
        elif self.mode != "topic_only":
            raise RuntimeError("unknown input_mode: %s" % self.mode)

        self.create_timer(0.1, self.on_tick)
        self.get_logger().info(
            "password_node ready (mode=%s, length=%d, attempts=%d)"
            % (self.mode, self.verifier.password_length, self.verifier.max_attempts))

    def now(self) -> float:
        return self.get_clock().now().nanoseconds / 1e9

    def publish(self, events) -> None:
        for ev in events:
            self.event_pub.publish(String(data=json.dumps(ev.to_dict())))
            self.get_logger().info("event: %s (attempts left %d)"
                                   % (ev.type.value, ev.attempts_left))
            if ev.type in RESULT_FOR_EVENT:
                self.result_pub.publish(String(data=RESULT_FOR_EVENT[ev.type]))

    def on_start(self, _msg) -> None:
        self.debouncer.reset()
        self.publish(self.verifier.start(self.now()))

    def on_cancel(self, _msg) -> None:
        self.publish(self.verifier.cancel())

    def on_token(self, msg) -> None:
        self.publish(self.verifier.feed(msg.data.strip(), self.now()))

    def handle_raw(self, raw) -> None:
        token = self.debouncer.update(raw, self.now())
        if token is not None:
            self.publish(self.verifier.feed(token, self.now()))

    def on_fingers(self, msg) -> None:
        if self.verifier.active:
            self.handle_raw(msg.data if msg.data >= 0 else None)

    def on_image(self, msg) -> None:
        # MediaPipe only runs during a session, to keep CPU free for YOLO.
        if not self.verifier.active:
            return
        self._frame_i += 1
        if self._frame_i % self.every_n:
            return
        frame = self.bridge.imgmsg_to_cv2(msg, desired_encoding="bgr8")
        self.handle_raw(self.counter.count(frame))

    def on_tick(self) -> None:
        self.publish(self.verifier.tick(self.now()))

    def destroy_node(self):
        if self.counter is not None:
            self.counter.close()
        super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    node = PasswordNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
