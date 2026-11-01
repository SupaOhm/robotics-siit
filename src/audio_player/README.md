
# Audio Player — Lane 4

ROS 2 audio playback package for the AI Gesture-Controlled
Security Robot.

## Features

- Plays pre-recorded English WAV clips
- Queues incoming audio requests
- Applies cooldown only to `found_*` clips
- Interrupts current playback when `alert` is received
- Supports Windows playback and Linux playback via `aplay`

## ROS 2 Interface

Topic: `/audio/play`
Type: `std_msgs/msg/String`

The message contains a clip ID without the `.wav` extension.

Example: `found_chair`

## Available Clips

- found_chair
- found_table
- found_bottle
- found_obstacle
- password_prompt
- password_wrong
- password_denied
- password_correct
- operator_allowed
- alert
- blocking

More object clips can be added after confirmation
of Lane 2's object labels.

## Tests

From the package directory:

```bash
python -m pytest test -v
```

The tests do not require ROS 2 or physical audio hardware.

## ROS 2 Build (Ubuntu / Robot)

```bash
cd ~/robotics-siit
colcon build --packages-select audio_player --symlink-install
source install/setup.bash
ros2 run audio_player audio_node
```

Test from another ROS 2 terminal:

```bash
ros2 topic pub --once /audio/play std_msgs/msg/String "{data: found_chair}"
```

The Linux system needs `aplay` (from `alsa-utils`)
and a configured audio output device.

## Status

- Windows WAV playback: tested
- Queue / cooldown / alert priority: 4 unit tests passed
- ROS 2 build: pending
- Physical robot speaker: pending

## Integration

The package follows `docs/interfaces.md` (Audio D10/D25).
