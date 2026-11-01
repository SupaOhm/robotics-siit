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
| `/obstacle/distance` | `std_msgs/Float32` | out | Filtered front distance in metres, one per reading |
| `/obstacle/detected` | `std_msgs/Bool` | out | Sent at a fixed 10 Hz. `True` while blocked, from start-up until the first valid reading, and while the sensor is silent |
| `/avoidance/start` | `std_msgs/Empty` | in | Turn away from the obstacle in front |
| `/avoidance/cancel` | `std_msgs/Empty` | in | Stop turning |
| `/avoidance/cmd_vel` | `geometry_msgs/Twist` | out | Turn command (`angular.z` only), sent only while turning |
| `/avoidance/result` | `std_msgs/String` | out | One per turn: `done`, `failed` or `cancelled` |

Expected use by the main state machine:

```
/obstacle/detected == True    -> stop, classify with YOLO, name it / password check
named the object              -> publish /avoidance/start, forward /avoidance/cmd_vel
/avoidance/result == "done"   -> give driving back to the operator
/avoidance/result == "failed" -> boxed in or sensor lost: stop, ask the operator
```

The node never drives forward and never writes `/cmd_vel` itself. Only the
state machine writes `/cmd_vel`, and in `AVOID` it forwards
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
- **Turn:** at 1 rad/s. It stops once it has turned at least 30 degrees and
  the front has stayed clear (0.40 m) for 0.3 s. After 270 degrees with no
  clear front it reports `failed`. Without odometry the node estimates the
  angle as speed x time, so tune `turn_speed` on the real robot.
- **Sensor silent for 0.5 s:** `/obstacle/detected` stays `True` until
  readings come back, and any turn ends as `failed`. A turn requested before
  the first reading also fails.
- **Turn time:** the state machine cancels a turn after 10 s with no result.
  At 1 rad/s the longest turn (270 degrees) takes about 4.7 s. Keep
  `turn_speed` above about 0.5 rad/s, or lower `max_turn_deg` with it.

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
