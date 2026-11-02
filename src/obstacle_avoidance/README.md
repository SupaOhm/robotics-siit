# obstacle_avoidance (Lane 3, navigation and avoidance)

Reads the distance sensor, filters the noise, and tells the main state
machine when something is in front of the robot. After the robot has
stopped and named the obstacle, the state machine asks this node to turn
away. The node turns in place until the front is clear, then reports
`done` so the operator can drive again.

We haven't picked the sensor yet (PLAN.md, Lane 1 question 4), so the node
takes either one:

| `input_type` | Sensor | Message | Turn direction |
|---|---|---|---|
| `scan` (default) | LiDAR | `sensor_msgs/LaserScan` | Toward the side with more room |
| `range` | Ultrasonic | `sensor_msgs/Range` | Always `default_direction` (front only) |

ROS 2 (`ament_python`) package. The logic is plain Python, so you can test
it without ROS.

## Interface (for the main state machine)

| Topic | Type | Direction | Meaning |
|---|---|---|---|
| `/scan` or `/ultrasonic/range` | `LaserScan` / `Range` | in | Raw sensor (topic names are parameters) |
| `/imu/data_raw` | `sensor_msgs/Imu` | in | Gyro z from the Yahboom base driver, to measure the turn (`imu_topic`, optional) |
| `/obstacle/distance` | `std_msgs/Float32` | out | Filtered front distance in metres, one per reading |
| `/obstacle/detected` | `std_msgs/Bool` | out | Sent at a fixed 10 Hz. `True` while blocked, from start-up until the first valid reading, and while the sensor is silent |
| `/avoidance/start` | `std_msgs/Empty` | in | Turn away from the obstacle in front |
| `/avoidance/cancel` | `std_msgs/Empty` | in | Stop turning |
| `/avoidance/cmd_vel` | `geometry_msgs/Twist` | out | Turn command, sent only while turning. With `diff` (the default) `linear.x` is 0. With `ackermann` it is negative while the robot backs up and positive while it arcs forward |
| `/avoidance/result` | `std_msgs/String` | out | One per turn: `done`, `failed` or `cancelled` |

Expected use by the main state machine:

```
/obstacle/detected == True    -> stop, classify with YOLO, name it / password check
named the object              -> publish /avoidance/start, forward /avoidance/cmd_vel
/avoidance/result == "done"   -> give driving back to the operator
/avoidance/result == "failed" -> boxed in or sensor lost: stop, ask the operator
```

The node only moves the robot during a turn and never writes `/cmd_vel`
itself. Only the state machine writes `/cmd_vel`, and in `AVOID` it forwards
`/avoidance/cmd_vel` (contract D2). For a bench test without the state
machine, launch with `cmd_vel_topic:=/cmd_vel`.

## How it decides

- **Front (LiDAR):** the closest point in a corridor 0.20 m either side of
  the robot's centre line, measured straight ahead. An earlier +-15 degree
  cone was narrower than the robot, and in CoppeliaSim it missed obstacles at
  the robot's shoulders until 0.17 m. Set `corridor_half_width` to half the
  A1's width plus a margin. Beams with no return (0 from the YDLIDAR driver)
  are skipped.
- **Filter:** median of the last 5 readings. NaN and readings under 2 cm
  get dropped. `inf` and anything past 4 m count as 4 m.
- **Threshold with hysteresis:** blocked at 0.30 m or closer, clear again
  only at 0.40 m or farther. A reading that hovers around 0.30 m does not
  toggle the state.
- **Turn (`drive_type: diff`, the default):** purin checked our A1: it has
  mecanum wheels and turns in place. The node turns at 1 rad/s. Done once
  the corridor ahead has stayed clear (0.40 m) for 0.3 s and the robot has
  turned at least 30 degrees. After 270 degrees it reports `failed`.

  Mecanum wheels slip when they turn in place, so the turned angle comes
  from the IMU gyro (`/imu/data_raw`). With no IMU it is speed x time.
  Speed x time also caps the turn: a robot that doesn't turn still reports
  `failed` after 4.7 s.
- **Turn on a car-like base (`drive_type: ackermann`):** for a base that
  can't turn in place. The A1 doesn't need it, and nobody has run it on a
  robot yet. It does a three-point turn:
  1. Back up at 0.15 m/s on full lock, so the nose swings away. Stop after
     30 degrees, 0.25 m, or when something is 0.20 m behind (LiDAR only).
  2. Drive forward on full lock the same way round. Done once the corridor
     ahead has stayed clear (0.40 m) for 0.3 s and the robot has turned at
     least 30 degrees. If the front closes to 0.20 m, back up again.
  3. After 3 backing phases, or 270 degrees, it reports `failed`.

  The turned angle comes from the IMU, or from the commands if there's no
  IMU. Set `wheelbase` and `max_steer_deg` for the base. During a turn the
  node also reacts to the latest scan before the filter: an arcing car
  sweeps side obstacles into its path, and in CoppeliaSim the 0.3 s filter
  delay let the front close to 0.05 m.
- **Sensor silent for 0.5 s:** `/obstacle/detected` stays `True` until
  readings come back, and any turn ends as `failed`. A turn requested before
  the first reading also fails.
- **Turn time:** the state machine cancels a turn after 10 s with no result.
  On `diff` the longest turn (270 degrees at 1 rad/s) takes 4.7 s. On
  `ackermann` 270 degrees at the guessed full-lock rate (0.54 rad/s) takes
  8.7 s, so set `max_turn_deg: 180` there.

Every number above is a parameter in [config/avoidance.yaml](config/avoidance.yaml).

## Build and run

```bash
cd <workspace>            # the repo root, which holds src/
colcon build --packages-select obstacle_avoidance
source install/setup.bash

ros2 launch obstacle_avoidance avoidance.launch.py                    # LiDAR
ros2 launch obstacle_avoidance avoidance.launch.py input_type:=range  # ultrasonic

# Try a turn by hand
ros2 topic echo /obstacle/distance
ros2 topic pub --once /avoidance/start std_msgs/msg/Empty
ros2 topic echo /avoidance/result
```

Check the Yahboom sensor topic with `ros2 topic list` and set `scan_topic`
or `range_topic` to match. If the LiDAR's 0 degree points backward, set
`front_angle_deg: 180.0`.

## Try it in CoppeliaSim (no ROS)

[`tools/sim_avoidance.py`](../../tools/sim_avoidance.py) drives the course's
Lab 03 robot (differential drive, Hokuyo LiDAR) with this package's filter,
detector and avoider over CoppeliaSim's ZMQ API. It runs on macOS too. The
lab scene isn't in the repo, so pass the path to your copy:

```bash
pip install coppeliasim-zmqremoteapi-client
# open CoppeliaSim first
python tools/sim_avoidance.py ~/Robotic/Lab3_mat/Lab3_scene.ttt
```

It puts a wall 1 m ahead and prints every stop and turn. By default it
turns the lab robot in place on its own wheels (`--drive diff`, as on the
A1). `--drive ackermann` moves it like a car-like base instead (bicycle
model, no turning at zero speed). The lab's
LiDAR sees 240 degrees, so the rear is blind in the sim. Don't save over the
lab scene afterwards.

## Tests

```bash
cd src/obstacle_avoidance
python -m pytest test
```

The tests cover the filter, the hysteresis, LiDAR sector maths and the turn
logic. They don't need ROS or a sensor.

## Files

```
obstacle_avoidance/
  range_filter.py   median filter, glitch and out-of-range handling
  detector.py       stop / clear threshold with hysteresis
  scan.py           LaserScan -> front (corridor) / left / right distances
  avoider.py        turn-away state machine
  avoidance_node.py thin ROS 2 node
config/avoidance.yaml
launch/avoidance.launch.py
```

The topic contract lives in `docs/interfaces.md` (D5 for this package).

## Open questions

1. LiDAR or ultrasonic? D19 says LiDAR if the A1 has one; confirmed at bring-up
2. Stop and clear distances: 0.30 / 0.40 m are first guesses. Tune them on
   the robot with the demo obstacles.
