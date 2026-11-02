"""Try obstacle_avoidance in CoppeliaSim, without ROS.

Uses the course's Lab 03 scene: a differential-drive robot (/body, wheels J1
and J2) with a Hokuyo LiDAR that publishes each sweep to the
customData.lidarScan buffer. The scene isn't in this repo; pass its path.

    pip install coppeliasim-zmqremoteapi-client
    # open CoppeliaSim (it serves the ZMQ remote API on port 23000), then:
    python tools/sim_avoidance.py ~/Robotic/Lab3_mat/Lab3_scene.ttt

The script reopens the scene, removes the lab's own /body/online controller,
copies Obstacle[0] as a wall ahead of the robot and runs the simulation step
by step. ZMQ stands in for ROS: the script reads the LiDAR, runs this
package's filter, detector and avoider, and sets the wheel speeds. The
robot's heading in the sim stands in for the IMU. A small loop stands in
for Lane 1's state machine: drive, stop when an obstacle appears (D28),
pause like ANNOUNCE, AVOID, drive again.

Nothing is saved: don't save over the lab scene in CoppeliaSim afterwards.
"""

import argparse
import math
import sys
import threading
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src" / "obstacle_avoidance"))

from obstacle_avoidance.avoider import Avoider, EventType
from obstacle_avoidance.detector import ObstacleDetector
from obstacle_avoidance.range_filter import RangeFilter
from obstacle_avoidance.scan import front_left_right

WHEEL_RADIUS = 0.05   # m, Lab 03/04 robot (Lab 04 main.py)
TRACK = 0.30          # m, effective wheel track (Lab 04 main.py)
DRIVE_SPEED = 0.10    # m/s, the lab's FORWARD_SPEED 2.0 rad/s
ANNOUNCE_PAUSE = 1.0  # s stopped before AVOID


def load_params(path):
    """The flat key: value lines of avoidance.yaml (no PyYAML needed)."""
    params = {}
    for line in open(path):
        line = line.split("#")[0].strip()
        key, _, value = line.partition(":")
        value = value.strip().strip('"')
        if not value:
            continue
        try:
            params[key.strip()] = int(value) if value.lstrip("-").isdigit() else float(value)
        except ValueError:
            params[key.strip()] = value
    return params


def wrap(angle):
    return math.atan2(math.sin(angle), math.cos(angle))


def run(sim, args, log):
    P = load_params(args.config)

    sim.loadScene(str(Path(args.scene).expanduser().resolve()))
    sim.removeObjects([sim.getObject("/body/online")])
    body = sim.getObject("/body")
    left_motor, right_motor = sim.getObject("/body/J1"), sim.getObject("/body/J2")
    hokuyo = sim.getObject("/body/Hokuyo")

    src = sim.getObject("/Obstacle[0]")
    wall = sim.copyPasteObjects([src], 0)[0]
    sim.setObjectAlias(wall, "TestWall")
    bp = sim.getObjectPosition(body, sim.handle_world)
    wp = sim.getObjectPosition(src, sim.handle_world)
    sim.setObjectPosition(wall, sim.handle_world, [bp[0], bp[1] - args.wall_ahead, wp[2]])
    half_len = sim.getShapeBB(body)[0][1] / 2
    log("wall %.1f m ahead; LiDAR to front of robot %.2f m" % (args.wall_ahead, half_len))
    log("corridor +-%.2f m, stop %.2f m, clear %.2f m, turn %.1f rad/s"
        % (P["corridor_half_width"], P["stop_distance"], P["clear_distance"], P["turn_speed"]))

    def wheels(v, w):
        sim.setJointTargetVelocity(left_motor, (v - w * TRACK / 2) / WHEEL_RADIUS)
        sim.setJointTargetVelocity(right_motor, (v + w * TRACK / 2) / WHEEL_RADIUS)

    def heading():
        m = sim.getObjectMatrix(body, sim.handle_world)
        return math.atan2(-m[5], -m[1])  # the robot drives along its body -Y

    def make_filter():
        return RangeFilter(P["filter_window"], P["min_range"], P["max_range"])
    front_f, left_f, right_f = make_filter(), make_filter(), make_filter()
    detector = ObstacleDetector(P["stop_distance"], P["clear_distance"])
    avoider = Avoider(P["clear_distance"], P["turn_speed"], math.radians(P["min_turn_deg"]),
                      math.radians(P["max_turn_deg"]), P["clear_time"], int(P["default_direction"]))
    side = lambda f: math.inf if f.value is None else f.value

    sim.setStepping(True)
    sim.startSimulation()
    state, was_blocked, last_scan = "DRIVE", False, None
    t, t_stopped, yaw_start, avoids, closest_seen = 0.0, 0.0, 0.0, 0, math.inf
    wall_start = time.monotonic()
    try:
        while t < args.seconds:
            sim.step()
            t = sim.getSimulationTime()
            if args.realtime:
                time.sleep(max(0.0, t - (time.monotonic() - wall_start)))
            data = sim.getBufferProperty(hokuyo, "customData.lidarScan", {"noError": True})
            scan = sim.unpackTable(data) if data else None
            if scan and scan["timestamp"] != last_scan:
                last_scan = scan["timestamp"]
                f, l, r = front_left_right(
                    scan["ranges"], scan["angleMin"], scan["angleIncrement"],
                    math.radians(P["front_angle_deg"]), P["corridor_half_width"],
                    math.radians(P["side_half_width_deg"]), max(scan["rangeMin"], P["min_range"]))
                front_f.update(f)
                left_f.update(l)
                right_f.update(r)
                hits = [x for x in scan["ranges"] if x >= scan["rangeMin"]]
                closest_seen = min([closest_seen] + hits)
                if front_f.value is not None:
                    detector.update(front_f.value)
            front = front_f.value
            if front is None:
                wheels(0, 0)
                continue

            if state == "DRIVE":
                if detector.blocked and not was_blocked:
                    wheels(0, 0)
                    state, t_stopped = "STOPPED", t
                    log("t=%5.2f  obstacle at %.3f m, stop" % (t, front))
                else:
                    wheels(0 if detector.blocked else DRIVE_SPEED, 0)
            elif state == "STOPPED":
                if t - t_stopped >= ANNOUNCE_PAUSE:
                    ev = avoider.start(t, side(left_f), side(right_f), heading())[0]
                    yaw_start, state = heading(), "AVOID"
                    log("t=%5.2f  stopped at %.3f m (gap at the front %.3f m), left %.2f right %.2f, turn %s"
                        % (t, front, front - half_len, side(left_f), side(right_f),
                           "left" if ev.direction > 0 else "right"))
            elif state == "AVOID":
                events = avoider.tick(t, front, heading())
                wheels(0, avoider.angular_velocity)
                for ev in events:
                    avoids += 1
                    log("t=%5.2f  %s: turned %.0f deg (avoider counted %.0f deg), front %.2f m"
                        % (t, ev.type.value, math.degrees(abs(wrap(heading() - yaw_start))),
                           math.degrees(avoider.turned_angle), front))
                    state = "DRIVE" if ev.type == EventType.DONE else "FAILED"
            if state == "FAILED":
                break
            was_blocked = detector.blocked
        p = sim.getObjectPosition(body, sim.handle_world)
        log("t=%5.2f  end: %d avoids, robot at (%.2f, %.2f), state %s" % (t, avoids, p[0], p[1], state))
        log("closest LiDAR reading all run: %.3f m (LiDAR to front of robot %.2f m)" % (closest_seen, half_len))
    finally:
        wheels(0, 0)
        sim.stopSimulation()
        sim.setStepping(False)


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("scene", help="path to Lab3_scene.ttt, on the machine running CoppeliaSim")
    parser.add_argument("--config", default=str(REPO / "src/obstacle_avoidance/config/avoidance.yaml"))
    parser.add_argument("--seconds", type=float, default=45.0, help="simulated time to run")
    parser.add_argument("--realtime", action="store_true", help="run at real speed, to watch it")
    parser.add_argument("--wall-ahead", type=float, default=1.0, help="m from the robot to the wall")
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--port", type=int, default=23000)
    args = parser.parse_args()

    def target():
        from coppeliasim_zmqremoteapi_client import RemoteAPIClient
        run(RemoteAPIClient(args.host, args.port).require("sim"), args, print)

    # The ZMQ client blocks forever while CoppeliaSim shows a dialog.
    worker = threading.Thread(target=target, daemon=True)
    worker.start()
    worker.join(300)
    if worker.is_alive():
        sys.exit("CoppeliaSim stopped answering. Close any open dialog in it and run again.")


if __name__ == "__main__":
    main()
