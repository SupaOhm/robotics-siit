"""Lane 3's bring-up checks on the robot, in one command.

Run it on the robot with the base driver and the LiDAR up and the state
machine stopped: test 4 publishes /cmd_vel itself.

    source /opt/ros/humble/setup.bash
    python3 tools/lane3_bringup_check.py

It covers the Lane 3 rows of docs/robot-setup.md §3 and ends with a summary
to paste there:

1. /scan and /imu/data_raw arrive, how fast, and with which QoS
2. a box 0.3 m in front: which way the LiDAR's 0 deg points, and what
   obstacle_avoidance would read
3. a cup, then a bottle, 0.3 m in front: does the LiDAR beam see them?
4. a 2 s turn in place at +0.5 rad/s: does the IMU read about +0.5 rad/s?

--no-objects skips 2 and 3, --no-turn skips 4. Robot width and the
LiDAR-to-bumper gap still need a tape measure.
"""

import argparse
import math
import statistics
import sys
import threading
import time
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src" / "obstacle_avoidance"))
sys.path.insert(0, str(REPO / "tools"))

from obstacle_avoidance.scan import front_left_right  # noqa: E402
from sim_avoidance import load_params  # noqa: E402

TURN_SPEED = 0.5  # rad/s, the robot-setup.md turn-in-place test
TURN_TIME = 2.0   # s
SETTLE = 0.5      # s at the start of the turn left out of the IMU average


def wrap(angle):
    return math.atan2(math.sin(angle), math.cos(angle))


def judge_rate(name, hz, good, ok, why):
    if hz >= good:
        return "PASS", "%s at %.1f Hz" % (name, hz)
    if hz >= ok:
        return "WARN", "%s at %.1f Hz, %s" % (name, hz, why)
    return "FAIL", "%s at %.1f Hz, %s" % (name, hz, why)


def closest_return(ranges, angle_min, angle_increment, max_dist=1.0, min_valid=0.02):
    """(distance, angle in deg) of the closest valid return within max_dist,
    or None. With one box in front, its angle is where 0 deg points."""
    best = None
    for i, r in enumerate(ranges):
        if math.isnan(r) or r < min_valid or r > max_dist:
            continue
        if best is None or r < best[0]:
            best = (r, math.degrees(wrap(angle_min + i * angle_increment)))
    return best


def mean_angle(degrees):
    """Mean of angles in deg, so +179 and -179 average to 180, not 0."""
    rad = [math.radians(a) for a in degrees]
    return math.degrees(math.atan2(sum(map(math.sin, rad)), sum(map(math.cos, rad))))


def judge_front_angle(angle):
    if abs(angle) <= 20:
        return "PASS", "box seen at %+.0f deg: front_angle_deg 0.0 is right" % angle
    if abs(angle) >= 160:
        return "WARN", "box seen at %+.0f deg: set front_angle_deg: 180.0" % angle
    return "WARN", "box seen at %+.0f deg: 0 deg doesn't point ahead; set front_angle_deg to about %.0f" % (angle, angle)


def judge_low_object(name, front):
    if front <= 0.45:
        return "PASS", "%s at 0.3 m: the node reads %.2f m" % (name, front)
    if front <= 0.6:
        return "WARN", "%s at 0.3 m: the node reads %.2f m, the beam only clips it" % (name, front)
    return "FAIL", "%s at 0.3 m: the node reads %.2f m, so it is below the beam and never stops the robot" % (name, front)


def judge_imu(rates, commanded):
    if not rates:
        return "FAIL", "no IMU readings during the turn"
    mean = statistics.mean(rates)
    if abs(mean) < 0.1 * commanded:
        return "FAIL", "IMU z %.3f rad/s for %.1f commanded: the robot didn't turn, or this isn't the base's IMU" % (mean, commanded)
    if mean < 0:
        return "FAIL", "IMU z %.2f for +%.1f commanded: the sign is flipped, so every AVOID fails" % (mean, commanded)
    if mean > 10 * commanded:
        return "FAIL", "IMU z %.1f for %.1f commanded: that looks like deg/s; the node needs rad/s" % (mean, commanded)
    if 0.5 * commanded <= mean <= 1.5 * commanded:
        return "PASS", "IMU z %.2f rad/s for %.1f commanded (%.0f%%)" % (mean, commanded, 100 * mean / commanded)
    return "WARN", "IMU z %.2f rad/s for %.1f commanded: slip, or a different scale" % (mean, commanded)


def run(args):
    import rclpy
    from geometry_msgs.msg import Twist
    from rclpy.node import Node
    from rclpy.qos import qos_profile_sensor_data
    from sensor_msgs.msg import Imu, LaserScan

    P = load_params(args.config)
    front_deg = [P["front_angle_deg"]]  # step 2 corrects it if the box says otherwise
    results = []

    def report(status, text):
        results.append((status, text))
        print("  %-4s %s" % (status, text), flush=True)

    class Probe(Node):
        def __init__(self):
            super().__init__("lane3_bringup_check")
            self.scans, self.imus = [], []
            self.create_subscription(LaserScan, args.scan_topic, self.on_scan, qos_profile_sensor_data)
            self.create_subscription(Imu, args.imu_topic, self.on_imu, qos_profile_sensor_data)
            self.cmd_pub = self.create_publisher(Twist, args.cmd_vel_topic, 10)

        def on_scan(self, msg):
            self.scans.append((time.monotonic(), msg))

        def on_imu(self, msg):
            self.imus.append((time.monotonic(), msg.angular_velocity.z))

        def send(self, angular):
            cmd = Twist()
            cmd.angular.z = angular
            self.cmd_pub.publish(cmd)

        def since(self, items, t0):
            return [x for t, x in items if t >= t0]

        def reliability(self, topic):
            infos = self.get_publishers_info_by_topic(topic)
            return ", ".join(sorted({i.qos_profile.reliability.name for i in infos})) or "no publisher"

    rclpy.init()
    node = Probe()
    threading.Thread(target=rclpy.spin, args=(node,), daemon=True).start()

    def front_reading(seconds=1.0):
        """Median of what obstacle_avoidance's corridor would read."""
        t0 = time.monotonic()
        time.sleep(seconds)
        fronts = []
        for s in node.since(node.scans, t0):
            front, _, _ = front_left_right(
                s.ranges, s.angle_min, s.angle_increment,
                math.radians(front_deg[0]), P["corridor_half_width"],
                math.radians(P["side_half_width_deg"]), max(s.range_min, P["min_range"]))
            if not math.isnan(front):
                fronts.append(min(front, P["max_range"]))
        return statistics.median(fronts) if fronts else None

    def ask(text):
        if args.yes:
            print("  ...  " + text, flush=True)
            return True
        return input("  >>>  %s [Enter = go, s = skip] " % text).strip().lower() != "s"

    try:
        print("1. Topics (3 s)", flush=True)
        t0 = time.monotonic()
        time.sleep(3.0)
        scans, imus = node.since(node.scans, t0), node.since(node.imus, t0)
        if scans:
            report(*judge_rate(args.scan_topic, len(scans) / 3.0, 8, 4,
                               "sensor_timeout is 0.5 s, so a few late scans go stale"))
            s = scans[-1]
            zeros = sum(1 for r in s.ranges if r == 0.0) / max(len(s.ranges), 1)
            report("INFO", "%s: %d beams, %.0f to %.0f deg, %.0f%% zero, QoS %s" % (
                args.scan_topic, len(s.ranges), math.degrees(s.angle_min),
                math.degrees(s.angle_min + (len(s.ranges) - 1) * s.angle_increment),
                100 * zeros, node.reliability(args.scan_topic)))
        else:
            report("FAIL", "%s: nothing in 3 s (ros2 topic list, ROS_DOMAIN_ID)" % args.scan_topic)
        if imus:
            report(*judge_rate(args.imu_topic, len(imus) / 3.0, 10, 5,
                               "imu_timeout is 0.2 s, so the yaw keeps dropping out"))
            report("INFO", "%s: QoS %s" % (args.imu_topic, node.reliability(args.imu_topic)))
        else:
            report("FAIL", "%s: nothing in 3 s; set imu_topic, or \"\" to count speed x time" % args.imu_topic)

        if scans and not args.no_objects:
            print("2. Which way is front", flush=True)
            if ask("Put a box 0.3 m straight ahead of the robot, nothing else within 1 m"):
                t0 = time.monotonic()
                time.sleep(1.0)
                hits = [closest_return(s.ranges, s.angle_min, s.angle_increment,
                                       min_valid=max(s.range_min, P["min_range"]))
                        for s in node.since(node.scans, t0)]
                hits = [h for h in hits if h]
                if hits:
                    angle = mean_angle(a for _, a in hits)
                    report(*judge_front_angle(angle))
                    if abs(wrap(math.radians(angle - front_deg[0]))) > math.radians(20):
                        front_deg[0] = round(angle)
                        report("INFO", "the next checks look along %+d deg, where the box was" % front_deg[0])
                    front = front_reading()
                    if front is not None:
                        report("INFO", "box: closest return %.2f m, obstacle_avoidance reads %.2f m (stops at %.2f)"
                               % (statistics.median(d for d, _ in hits), front, P["stop_distance"]))
                else:
                    report("FAIL", "no return within 1 m: is the box in the LiDAR's view?")
            print("3. Low objects", flush=True)
            for name in ("cup", "bottle"):
                if ask("Put a %s on the floor 0.3 m straight ahead, nothing else in front" % name):
                    front = front_reading()
                    if front is None:
                        report("FAIL", "%s: no valid scans" % name)
                    else:
                        report(*judge_low_object(name, front))

        if not args.no_turn:
            print("4. Turn in place", flush=True)
            others = len(node.get_publishers_info_by_topic(args.cmd_vel_topic)) - 1
            if others > 0 and not args.force:
                report("SKIP", "turn: %d other publisher(s) on %s; stop the state machine, or use --force"
                       % (others, args.cmd_vel_topic))
            elif not imus:
                report("SKIP", "turn: no IMU to read")
            elif ask("The robot turns left on the spot for %.0f s. Clear 0.5 m around it" % TURN_TIME):
                t0 = time.monotonic()
                while time.monotonic() - t0 < TURN_TIME:
                    node.send(TURN_SPEED)
                    time.sleep(0.05)
                for _ in range(10):
                    node.send(0.0)
                    time.sleep(0.05)
                rates = [z for t, z in node.imus if t0 + SETTLE <= t <= t0 + TURN_TIME]
                report(*judge_imu(rates, TURN_SPEED))
    finally:
        node.send(0.0)
        node.destroy_node()
        rclpy.shutdown()

    print("\nLane 3 bring-up, %s (tools/lane3_bringup_check.py):" % date.today())
    for status, text in results:
        print("- %s: %s" % (status, text))
    return 0 if all(s != "FAIL" for s, _ in results) else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", default=str(REPO / "src/obstacle_avoidance/config/avoidance.yaml"))
    parser.add_argument("--scan-topic", default="/scan")
    parser.add_argument("--imu-topic", default="/imu/data_raw")
    parser.add_argument("--cmd-vel-topic", default="/cmd_vel")
    parser.add_argument("--no-objects", action="store_true", help="skip the box, cup and bottle")
    parser.add_argument("--no-turn", action="store_true", help="skip the turn (publishes /cmd_vel)")
    parser.add_argument("--force", action="store_true", help="turn even if something else publishes /cmd_vel")
    parser.add_argument("--yes", action="store_true", help="don't wait for Enter between steps")
    sys.exit(run(parser.parse_args()))


if __name__ == "__main__":
    main()
