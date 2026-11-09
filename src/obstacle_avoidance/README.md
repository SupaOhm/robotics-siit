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
| `/obstacle/distance` | `std_msgs/Float32` | out | Filtered front distance from the front bumper in metres, one per reading |
| `/obstacle/detected` | `std_msgs/Bool` | out | Sent at a fixed 10 Hz. `True` while blocked, from start-up until the first valid reading, and while the sensor is silent |
| `/avoidance/start` | `std_msgs/Empty` | in | Turn away from the obstacle in front |
| `/avoidance/cancel` | `std_msgs/Empty` | in | Stop turning |
| `/avoidance/cmd_vel` | `geometry_msgs/Twist` | out | Turn command, sent only while turning: `angular.z` only, `linear.x` stays 0 |
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
  M1's width plus a margin. Beams with no return (0 from the YDLIDAR driver)
  are skipped.
- **Filter:** median of the last 5 readings. NaN and readings under 2 cm
  get dropped. `inf` and anything past 4 m count as 4 m.
- **Distances are from the front bumper:** the node subtracts
  `sensor_to_bumper` (0.15 m on the M1: the LiDAR sits behind the bumper)
  from what the sensor reads. Stop, clear and `/obstacle/distance` all use
  that.
- **Threshold with hysteresis:** blocked at 0.40 m or closer, clear again
  only at 0.50 m or farther. A reading that hovers around 0.40 m does not
  toggle the state.
- **Turn:** purin checked our M1: it has mecanum wheels and turns in
  place. The node turns at 1 rad/s. Done once the corridor ahead has stayed
  clear (0.50 m) for 0.3 s and the robot has turned at least 30 degrees.
  After 270 degrees it reports `failed`.

  Mecanum wheels slip when they turn in place, so the turned angle comes
  from the IMU gyro (`/imu/data_raw`). With no IMU, or after 0.3 s with no
  gyro reading, it is speed x time. Speed x time also caps the turn: a
  robot that doesn't turn still reports `failed` after 4.7 s.
- **Sensor silent for 0.5 s:** `/obstacle/detected` stays `True` until
  readings come back, and any turn ends as `failed`. A turn requested before
  the first reading also fails.
- **Turn time:** the state machine cancels a turn after 10 s with no result.
  The longest turn (270 degrees at 1 rad/s) takes 4.7 s.
- **Stopping distance:** the robot keeps moving for up to about 0.45 s after
  an obstacle comes within 0.40 m: up to 0.1 s to the next scan, about 0.2 s
  while the median of 5 catches up, up to 0.1 s to the next
  `/obstacle/detected`, then the state machine and the brakes. At 0.3 m/s
  the 0.45 s is about 13 cm, so the robot stops about 27 cm from the
  bumper. At the default 0.2 m/s it is about 9 cm, so about 31 cm. Keep
  `linear_speed` at 0.3 m/s or below.

  CoppeliaSim agrees (`tools/sim_avoidance.py --speed S --react 0.2`, the
  0.2 s standing in for the heartbeat and the state machine's tick). The lab
  robot came to rest this far from the LiDAR (run with stop at 0.30 m from
  the LiDAR, before distances were measured from the bumper):

  | Speed | Stopped at | Gap at the front |
  |---|---|---|
  | 0.1 m/s | 0.25 m | 15 cm |
  | 0.2 m/s (`robot_core`'s `linear_speed`) | 0.20 m | 10 cm |
  | 0.3 m/s | 0.17 m | 7 cm |

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
or `range_topic` to match. The M1's LiDAR 0 degree points backward, so the
yaml sets `front_angle_deg: 180.0`. Use 0.0 on a robot whose LiDAR faces forward.

The node subscribes to the sensor and the IMU with `qos_profile_sensor_data`
(best effort), which hears both best-effort and reliable publishers.
`ros2 topic info -v /scan` shows what the driver publishes.

During a turn, `angular_velocity.z` on `/imu/data_raw` should read about
the commanded rate in rad/s, positive turning left. A driver that sends
deg/s or flips the sign makes every turn fail.

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

It puts a wall 1 m ahead and prints every stop and turn. The robot's
heading in the sim stands in for the IMU, and `--realtime` slows the run
to real speed so you can watch it. The lab's
LiDAR sees 240 degrees, so the rear is blind in the sim. Don't save over the
lab scene afterwards.

## Tests

```bash
cd src/obstacle_avoidance
python -m pytest test
```

The tests cover the filter, the hysteresis, LiDAR sector maths, the gyro and
the turn logic. They don't need ROS or a sensor.

## Files

```
obstacle_avoidance/
  range_filter.py   median filter, glitch and out-of-range handling
  detector.py       stop / clear threshold with hysteresis
  scan.py           LaserScan -> front (corridor) / left / right distances
  avoider.py        turn-away state machine
  gyro.py           IMU gyro -> yaw, None while the gyro is silent
  avoidance_node.py thin ROS 2 node
config/avoidance.yaml
launch/avoidance.launch.py
```

The topic contract lives in `docs/interfaces.md` (D5 for this package).

## Open questions

1. LiDAR or ultrasonic? D19 says LiDAR if the M1 has one; confirmed at bring-up
2. Stop and clear distances: 0.40 / 0.50 m from the front bumper, less what
   the robot rolls. Before 9 Nov they were from the LiDAR, which sits about
   15 cm behind the bumper: 0.40 m from the LiDAR stopped it about 25 cm from
   the bumper (purin, 8 Nov), and 0.30 about 15 cm.

## Limitations

- **Low objects:** on the M1 the LiDAR beam is about 16 cm above the floor
  (Yahboom's drawing puts the top of the LiDAR at 181.4 mm). Anything lower,
  such as a cup, or a laptop on the floor, never stops the robot, so the
  detector never gets to name it. Use objects taller than 16 cm in the demo.
- **Clear and dark surfaces:** clear plastic and matt black can return no
  reading. On the robot the beam went through a clear Crystal bottle 0.3 m
  ahead and read 0.60 m.
- **Front only:** the robot stops for what is ahead. Backing up (`back`)
  has no obstacle check.
