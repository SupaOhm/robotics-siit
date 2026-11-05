"""Robot test of the password path only. NOT the final state machine.

  person on the camera -> "Say the password" -> answer recorded and checked
  -> correct: "Password correct", drive forward 2 s (only while the LiDAR
     says the path is clear)
  -> wrong 3 times: Telegram alert with the photo and the recorded answers

Run it instead of robot_core's state_machine (both publish /cmd_vel), with
password_node, detector_node, avoidance_node, audio_node, telegram_node and
camera_tilt running on the same ROS domain:

  python3 tools/password_test.py
"""

import json

import rclpy
from geometry_msgs.msg import Twist
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile
from std_msgs.msg import Bool, Empty, Int32, String

DETECT_EVERY = 1.0   # s between camera checks while watching
DRIVE_SPEED = 0.15   # m/s after a correct password
DRIVE_TIME = 2.0     # s
OBSTACLE_STALE = 1.0  # no /obstacle/detected this long -> don't drive
PASSWORD_TIMEOUT = 90.0  # 3 tries take ~17 s each with the countdown (measured)
OPERATOR_TIMEOUT = 40.0
COOLDOWN = 5.0       # s before looking for the next person
TILT_LEVEL, TILT_UP = 30, 90

WATCH, ASKING, DRIVING, ALERTED = "WATCH", "ASKING", "DRIVING", "ALERTED"
# What telegram_node and audio_node expect to see on /robot/state
ROBOT_STATE = {WATCH: "DRIVE", ASKING: "CHECKPOINT", DRIVING: "PASS",
               ALERTED: "WAIT_OPERATOR"}


class PasswordTest(Node):
    def __init__(self):
        super().__init__("password_test")
        self.state, self.since = WATCH, self.now()
        self.next_check = self.now() + 2.0
        self.request_id, self.alert_id, self.count = None, None, 0
        self.clear, self.clear_at = False, None

        pub = self.create_publisher
        self.cmd = pub(Twist, "/cmd_vel", 10)
        self.tilt = pub(Int32, "/camera/tilt",
                        QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL))
        self.state_pub = pub(String, "/robot/state", 10)
        self.detect = pub(String, "/detect/request", 10)
        self.audio = pub(String, "/audio/play", 10)
        self.alert = pub(String, "/telegram/alert", 10)
        self.pw_start = pub(Empty, "/password/start", 10)
        self.pw_cancel = pub(Empty, "/password/cancel", 10)

        sub = self.create_subscription
        sub(String, "/detect/result", self.on_detect, 10)
        sub(String, "/password/result", self.on_password, 10)
        sub(String, "/telegram/decision", self.on_decision, 10)
        sub(Bool, "/obstacle/detected", self.on_obstacle, 10)
        self.create_timer(0.1, self.tick)

        self.tilt.publish(Int32(data=TILT_LEVEL))
        self.get_logger().info("password test ready: watching the camera for a person")

    def now(self):
        return self.get_clock().now().nanoseconds * 1e-9

    def go(self, state):
        self.state, self.since = state, self.now()
        self.state_pub.publish(String(data=ROBOT_STATE[state]))
        self.get_logger().info("-> %s" % state)

    def watch_again(self):
        self.tilt.publish(Int32(data=TILT_LEVEL))
        self.next_check = self.now() + COOLDOWN
        self.go(WATCH)

    def on_obstacle(self, msg):
        self.clear, self.clear_at = not msg.data, self.now()

    def on_detect(self, msg):
        try:
            reply = json.loads(msg.data)
        except ValueError:
            return
        if self.state != WATCH or reply.get("id") != self.request_id:
            return
        if reply.get("kind") == "person":
            self.tilt.publish(Int32(data=TILT_UP))  # face for the Telegram photo
            self.go(ASKING)
            self.pw_start.publish(Empty())

    def on_password(self, msg):
        if self.state != ASKING:
            return
        if msg.data == "granted":
            self.audio.publish(String(data="password_correct"))
            self.tilt.publish(Int32(data=TILT_LEVEL))
            self.go(DRIVING)
        elif msg.data == "denied":
            self.count += 1
            self.alert_id = "pt%d" % self.count
            self.go(ALERTED)
            self.alert.publish(String(data=self.alert_id))
        else:  # cancelled
            self.watch_again()

    def on_decision(self, msg):
        try:
            reply = json.loads(msg.data)
        except ValueError:
            return
        if self.state == ALERTED and reply.get("id") == self.alert_id:
            self.get_logger().info("operator: %s" % reply.get("decision"))
            if reply.get("decision") == "allow":
                self.audio.publish(String(data="operator_allowed"))
            self.watch_again()

    def tick(self):
        now, in_state = self.now(), self.now() - self.since
        speed = 0.0
        if self.state == WATCH and now >= self.next_check:
            self.count += 1
            self.request_id = "pt-d%d" % self.count
            self.detect.publish(String(data=self.request_id))
            self.next_check = now + DETECT_EVERY
        elif self.state == ASKING and in_state >= PASSWORD_TIMEOUT:
            self.pw_cancel.publish(Empty())
            self.watch_again()
        elif self.state == DRIVING:
            fresh = self.clear_at is not None and now - self.clear_at < OBSTACLE_STALE
            if in_state >= DRIVE_TIME:
                self.watch_again()
            elif fresh and self.clear:
                speed = DRIVE_SPEED  # stops the moment the LiDAR sees anything
        elif self.state == ALERTED and in_state >= OPERATOR_TIMEOUT:
            self.get_logger().info("operator: no answer")
            self.watch_again()
        msg = Twist()
        msg.linear.x = speed
        self.cmd.publish(msg)  # every tick, so the wheels never keep an old speed


def main():
    rclpy.init()
    node = PasswordTest()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        if rclpy.ok():
            node.cmd.publish(Twist())
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
