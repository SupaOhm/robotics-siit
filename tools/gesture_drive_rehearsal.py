#!/usr/bin/env python3
"""Rehearse the gesture drive (#27 §4) on a laptop, without the robot.

Runs against the real `state_machine` (robot_core). This script stands in for
gesture_node and avoidance_node and checks the /cmd_vel that comes out.

Refuses to run unless ROS_LOCALHOST_ONLY=1 and ROS_DOMAIN_ID is not 42. It
publishes `/obstacle/detected false`, so on the robot's network it could
drive the real wheels.

Terminal 1, the state machine:
    ros2 run robot_core state_machine --ros-args --params-file src/robot_core/config/robot_core.yaml

Terminal 2, one of:
    python3 tools/gesture_drive_rehearsal.py          # scripted check, prints PASS/FAIL
    python3 tools/gesture_drive_rehearsal.py --stub   # only the obstacle stub, for a live
                                                      # gesture_node run; prints /cmd_vel changes
"""

import argparse
import os
import sys
import threading
import time

import rclpy
from geometry_msgs.msg import Twist
from rclpy.executors import SingleThreadedExecutor
from rclpy.node import Node
from rclpy.signals import SignalHandlerOptions
from std_msgs.msg import Bool, Empty, String

RATE = 10.0  # Hz, as gesture_node and avoidance_node publish


class Rehearsal(Node):
    def __init__(self):
        super().__init__("gesture_drive_rehearsal")
        self.word = None        # None: send no /gesture/command
        self.obstacle = False   # None: send no /obstacle/detected
        self.cmd = None         # last (linear.x, angular.z) and when
        self.cmd_at = 0.0
        self.state = None
        self.seen = {"/detect/request": 0, "/password/start": 0, "/password/cancel": 0}
        self.gesture_pub = self.create_publisher(String, "/gesture/command", 10)
        self.obstacle_pub = self.create_publisher(Bool, "/obstacle/detected", 10)
        self.create_subscription(Twist, "/cmd_vel", self.on_cmd, 10)
        self.create_subscription(String, "/robot/state", self.on_state, 10)
        self.create_subscription(String, "/detect/request", lambda _m: self.count("/detect/request"), 10)
        self.create_subscription(Empty, "/password/start", lambda _m: self.count("/password/start"), 10)
        self.create_subscription(Empty, "/password/cancel", lambda _m: self.count("/password/cancel"), 10)
        self.create_timer(1.0 / RATE, self.send)
        self.on_cmd_change = None

    def count(self, topic):
        self.seen[topic] += 1

    def send(self):
        if self.word is not None:
            self.gesture_pub.publish(String(data=self.word))
        if self.obstacle is not None:
            self.obstacle_pub.publish(Bool(data=self.obstacle))

    def on_cmd(self, msg):
        cmd = (round(msg.linear.x, 3), round(msg.angular.z, 3))
        if cmd != self.cmd and self.on_cmd_change:
            self.on_cmd_change(cmd, self.state)
        self.cmd, self.cmd_at = cmd, time.monotonic()

    def on_state(self, msg):
        if msg.data != self.state:
            print("   state -> %s" % msg.data)
        self.state = msg.data


def safe_env():
    domain = os.environ.get("ROS_DOMAIN_ID", "0")
    local = os.environ.get("ROS_LOCALHOST_ONLY", "0")
    if domain == "42" or local != "1":
        sys.exit("Refusing to run: needs ROS_LOCALHOST_ONLY=1 and ROS_DOMAIN_ID other than 42 "
                 "(now ROS_LOCALHOST_ONLY=%s, ROS_DOMAIN_ID=%s). This script fakes a clear path, so it must never reach "
                 "the robot. Set: export ROS_DOMAIN_ID=43 ROS_LOCALHOST_ONLY=1" % (local, domain))


def run_check(node, linear, angular):
    results = []

    def hold(word, obstacle, seconds):
        node.word, node.obstacle = word, obstacle
        time.sleep(seconds)

    def expect(name, want, state=None):
        got = node.cmd
        fresh = time.monotonic() - node.cmd_at < 0.5
        ok = fresh and got == want and (state is None or node.state == state)
        detail = "cmd_vel %s, state %s" % (got if fresh else "none for 0.5 s", node.state)
        results.append((ok, name, "want %s%s; got %s" % (
            want, ", %s" % state if state else "", detail)))
        print("%s  %s" % ("PASS" if ok else "FAIL", name))

    print("Waiting for state_machine ...")
    deadline = time.monotonic() + 10
    while node.state is None and time.monotonic() < deadline:
        time.sleep(0.1)
    if node.state is None:
        sys.exit("No /robot/state in 10 s: is state_machine running on this domain?")
    if node.state != "DRIVE":
        sys.exit("state_machine is in %s; restart it so it starts in DRIVE" % node.state)

    hold("none", False, 1.5)
    expect("none: wheels stopped", (0.0, 0.0), "DRIVE")
    hold("forward", False, 1.0)
    expect("forward", (linear, 0.0), "DRIVE")
    hold("back", False, 1.0)
    expect("back (in DRIVE it reverses)", (-linear, 0.0), "DRIVE")
    hold("left", False, 1.0)
    expect("left", (0.0, angular), "DRIVE")
    hold("right", False, 1.0)
    expect("right", (0.0, -angular), "DRIVE")
    hold("stop", False, 1.0)
    expect("stop", (0.0, 0.0), "DRIVE")

    hold("forward", False, 1.0)
    hold(None, False, 0.8)
    expect("gesture messages stop: wheels stop within 0.5 s (D4)", (0.0, 0.0), "DRIVE")

    hold("forward", None, 1.6)
    expect("no /obstacle/detected for 1 s: forward blocked (D5)", (0.0, 0.0), "DRIVE")
    hold("left", None, 1.0)
    expect("sensor silent: turning still works", (0.0, angular), "DRIVE")
    hold("forward", False, 1.0)
    expect("sensor back: forward again", (linear, 0.0), "DRIVE")

    requests = node.seen["/detect/request"]
    hold("forward", True, 1.0)
    expect("obstacle appears: CLASSIFY, wheels stopped", (0.0, 0.0), "CLASSIFY")
    asked = node.seen["/detect/request"] - requests
    results.append((asked >= 1, "/detect/request sent", "%d requests" % asked))
    print("%s  /detect/request sent" % ("PASS" if asked >= 1 else "FAIL"))

    print("   no detector here: waiting for the retry, then CHECKPOINT (about 6 s) ...")
    starts = node.seen["/password/start"]
    hold("forward", True, 6.0)
    asked = node.seen["/detect/request"] - requests
    started = node.seen["/password/start"] - starts
    expect("no detector reply after one retry: CHECKPOINT (D7)", (0.0, 0.0), "CHECKPOINT")
    ok = asked == 2 and started >= 1
    results.append((ok, "one retry, then /password/start",
                    "%d detect requests, %d password starts" % (asked, started)))
    print("%s  one retry, then /password/start" % ("PASS" if ok else "FAIL"))

    cancels = node.seen["/password/cancel"]
    hold("back", True, 1.6)
    hold("none", True, 0.5)
    cancelled = node.seen["/password/cancel"] - cancels
    expect("back held 1 s in CHECKPOINT: operator override to DRIVE (D11)", (0.0, 0.0), "DRIVE")
    results.append((cancelled >= 1, "override cancels the password", "%d cancels" % cancelled))
    print("%s  override cancels the password" % ("PASS" if cancelled >= 1 else "FAIL"))

    hold("forward", True, 1.0)
    expect("obstacle still there: forward blocked", (0.0, 0.0), "DRIVE")
    hold("none", False, 0.5)

    failed = [r for r in results if not r[0]]
    print("\n%d of %d passed" % (len(results) - len(failed), len(results)))
    for _ok, name, detail in failed:
        print("FAIL %s: %s" % (name, detail))
    return 1 if failed else 0


def run_stub(node):
    print("Obstacle stub: /obstacle/detected false at 10 Hz. Start gesture_node now. Ctrl-C stops.")
    print("Changes on /cmd_vel (linear.x, angular.z):")
    node.word = None
    node.on_cmd_change = lambda cmd, state: print("   %s  %s" % (cmd, state))
    while True:
        time.sleep(1)


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--stub", action="store_true",
                        help="only publish /obstacle/detected false, for a live gesture_node run")
    parser.add_argument("--linear", type=float, default=0.2, help="linear_speed in robot_core.yaml")
    parser.add_argument("--angular", type=float, default=1.0, help="angular_speed in robot_core.yaml")
    args = parser.parse_args()
    safe_env()
    sys.stdout.reconfigure(line_buffering=True)

    # Python handles Ctrl-C, so it raises KeyboardInterrupt here instead of
    # rclpy shutting down under the spin thread.
    rclpy.init(signal_handler_options=SignalHandlerOptions.NO)
    node = Rehearsal()
    executor = SingleThreadedExecutor()
    executor.add_node(node)
    threading.Thread(target=executor.spin, daemon=True).start()
    code = 0
    try:
        code = run_stub(node) if args.stub else run_check(node, args.linear, args.angular)
    except KeyboardInterrupt:
        pass
    finally:
        node.word, node.obstacle = None, None
        executor.shutdown()
        node.destroy_node()
        rclpy.try_shutdown()
    sys.exit(code)


if __name__ == "__main__":
    main()
