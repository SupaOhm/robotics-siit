# robot_core (Lane 1, state machine)

`state_machine`: the hub of the robot. It drives the wheels from gestures,
starts every other module over its topics, and is the **only** node that
publishes `/cmd_vel` (D2). It follows the state machine in
`docs/interfaces.md` (v0.3).

The logic is plain Python in `robot_core/machine.py`, so the tests run
anywhere without ROS. `state_machine_node.py` only converts messages.

## Run

```bash
colcon build --packages-select robot_core
source install/setup.bash
ros2 launch robot_core robot_core.launch.py
ros2 topic echo /robot/state
```

Timings and speeds are in `config/robot_core.yaml`.

## Test

```bash
cd src/robot_core
python -m pytest test
```

## Try it without the other nodes

```bash
# Gestures at 10 Hz (the robot stops 0.5 s after they end)
ros2 topic pub -r 10 /gesture/command std_msgs/String "data: none"
# A clear path, then an obstacle appearing
ros2 topic pub -r 10 /obstacle/detected std_msgs/Bool "data: false"
ros2 topic pub -r 10 /obstacle/detected std_msgs/Bool "data: true"
# Answer the detector request (use the id from /detect/request)
ros2 topic pub -1 /detect/result std_msgs/String '{data: "{\"id\": \"d1\", \"kind\": \"person\"}"}'
```

## Choices the contract leaves open

- Wheel commands go out on every tick (10 Hz), so the base never keeps an
  old speed.
- In `AVOID` the wheels follow `/avoidance/cmd_vel`, but a `stop` gesture
  or 0.5 s without gestures stops them.
- `back` held for 1 s counts from entering the state, and only once per
  hold: holding `back` out of `BLOCKING` turns away, and doesn't then also
  cancel that turn. A hold carried in from `DRIVE` (reversing) doesn't
  count at all: release `back` and hold it again, so reversing into a
  person never skips the password.
- Entering `CLASSIFY` sends a zero `/cmd_vel` at once, so the robot has
  stopped before the detector takes its frame.
- A `/detect/result` with a `kind` other than `object`, `person` or
  `unknown` goes to `CHECKPOINT`. A `/password/result` of `cancelled` is
  ignored, since the state machine only cancels as it leaves `CHECKPOINT`,
  so it belongs to an old session. Any other result except `granted` goes
  to `WAIT_OPERATOR`. An `/avoidance/result` other than `done` counts as
  `failed`.
- Obstacle silence never counts as a clear path, so it can't end
  `CHECKPOINT` as "person left".
