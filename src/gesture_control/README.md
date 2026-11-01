# gesture_control (Lane 2, hand gestures)

`gesture_node` runs on the operator's laptop. It reads the laptop webcam,
tracks one hand with MediaPipe and publishes a drive word on
`/gesture/command`. The state machine (`robot_core`) turns words into
speeds; this node never publishes `Twist` or `/cmd_vel`.

This follows the contract in `docs/interfaces.md` (v0.3: D3, D4, D11, D14,
D18). The logic is plain Python, so the tests run anywhere without ROS,
MediaPipe or a camera.

## Interface

| Topic | Type | Direction | Meaning |
|---|---|---|---|
| `/gesture/command` | `std_msgs/String` | out | `forward`, `back`, `left`, `right`, `stop` or `none` |

- Published at a fixed **10 Hz** from a timer, every tick, repeating the
  current word (D4).
- If the camera or MediaPipe gives no result for `stale_s` (0.3 s), the
  node publishes `none`. It never goes silent while running, and it
  publishes `none` on shutdown. (The robot also stops after 0.5 s of
  silence, D4.)
- `none` = no hand, or an open hand resting at the centre. `stop` is only
  ever the deliberate fist (D3).
- No decision gesture (D14): Allow / Deny is Telegram only.

## Gestures

The image is mirrored, so it works like a mirror: move your hand to your
right for `right`. Angles are measured around the frame centre: 0 = above,
+90 = right, 180 = below.

| Hand | Word |
|---|---|
| Fist (at most 1 of index..pinky extended; the thumb is ignored) | `stop` |
| Open hand above the centre (within 30 deg of straight up) | `forward` |
| Open hand below the centre (within 30 deg of straight down) | `back` |
| Open hand right of the centre | `right` (turn in place) |
| Open hand left of the centre | `left` (turn in place) |
| Open hand near the centre (inside `deadzone_radius`) | `none` |
| No hand | `none` (after `dropout_hold_s`) |

Guards against flicker and accidents:

- A new word must be seen `confirm_frames` (3) frames in a row before it is
  published.
- `back` needs `back_confirm_frames` (6), because holding `back` for 1 s is
  the operator override and the **Resume** gesture (D11).
- Near a sector border or the deadzone edge, the previous word sticks
  (`angle_hysteresis` 8 deg, `deadzone_hysteresis` 0.02).
- If the hand is lost for one or two frames, the word is held for
  `dropout_hold_s` (0.3 s, must be below 0.5 s), then becomes `none`.
  A held word is stamped with the time the hand was last seen, so if the
  camera also stalls, it goes stale `stale_s` after that, not after the
  hold: a drive word outlives the hand by at most 0.3 s plus one timer tick.
- After a camera or tracker failure the classifier and smoother reset, so
  the first word after the gap must be confirmed again.
- An open hand lowered below the centre while still in view reads as
  `back`. Drop the hand out of view or make a fist to rest. `back` is
  frame-counted (6 frames is 0.2 s at 30 fps); tune it on the laptop.
- A finger counts as extended if its tip is `extend_ratio` (1.1) times
  farther from the wrist than its middle joint. This works for either hand
  and any hand rotation. Pointing with one finger counts as a fist.

## Laptop setup (Ubuntu 22.04, ROS 2 Humble)

Every machine on the hotspot uses the same domain and RMW (D16, D17):

```bash
export ROS_DOMAIN_ID=42
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
sudo apt install ros-humble-rmw-cyclonedds-cpp
pip install mediapipe   # brings cv2 via opencv-contrib-python
```

Don't also install `opencv-python`: both provide `cv2` and overwrite each
other. If pip pulls a numpy that clashes with Humble's apt numpy, pin the
versions that work on the laptop (untested so far).

Download the hand model once. Don't commit it (`*.task` is gitignored).

```bash
wget -O ~/hand_landmarker.task \
  https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/latest/hand_landmarker.task
```

The node uses the MediaPipe Tasks API (`HandLandmarker`) with this model.
If the Tasks API is missing, or the model is missing or unreadable (for
example a partial download), and the installed MediaPipe still has the old
`mp.solutions`, it falls back to `mp.solutions.hands` and logs
a warning. If neither works, the node logs an error and keeps publishing
`none`.

## Build and run

```bash
cd <repo root>
colcon build --packages-select gesture_control
source install/setup.bash

# Webcam. show_window:=true draws the landmarks and the word, but it runs
# OpenCV GUI calls off the main thread (rclpy owns it): best effort, not yet
# tested on the laptop. webcam_demo below is the reliable overlay.
ros2 launch gesture_control gesture.launch.py show_window:=true
ros2 launch gesture_control gesture.launch.py camera_index:=1 model_path:=/path/to/hand_landmarker.task

# Keyboard, no camera (for Lane 1 / Lane 5 tests). Needs a terminal, so ros2 run:
ros2 run gesture_control gesture_node --ros-args -p input_mode:=keyboard
#   w forward, s back, a left, d right, space stop, x none
#   a word lasts key_hold_s (0.8 s) after the last key press; hold the key down
#   lowercase keys only; arrow and function keys are ignored
#   if the key reader stops (stdin closed, error), the node publishes none

ros2 topic echo /gesture/command
ros2 topic hz /gesture/command      # ~10 Hz
```

## Try it without ROS

```bash
pip install mediapipe
cd src/gesture_control
python -m gesture_control.webcam_demo --model ~/hand_landmarker.task
```

The window shows the hand skeleton, the centre deadzone circle, the finger
count, the angle and the word. Word changes are printed. ESC or q quits.

## Parameters

All thresholds are untuned starting values. Tune them on the operator's
laptop and camera. Defaults are in [config/gesture.yaml](config/gesture.yaml).

| Parameter | Default | Meaning |
|---|---|---|
| `input_mode` | `camera` | `camera` or `keyboard` |
| `camera_index` | 0 | OpenCV camera index |
| `model_path` | `~/hand_landmarker.task` | MediaPipe hand model |
| `show_window` | false | Draw landmarks and the word in a window |
| `publish_rate` | 10.0 | Hz, fixed |
| `stale_s` | 0.3 | No frame result this long: publish `none` (must be below 0.5) |
| `extend_ratio` | 1.1 | Finger extended if tip-wrist > PIP-wrist * ratio |
| `fist_max_fingers` | 1 | Extended fingers (thumb ignored) at or below this: `stop` |
| `deadzone_radius` | 0.12 | Centre zone for `none`, in frame heights |
| `deadzone_hysteresis` | 0.02 | Band around the deadzone edge |
| `forward_half_angle` | 30 | Degrees either side of up for `forward` |
| `back_min_angle` | 150 | Degrees from up beyond which it is `back` |
| `angle_hysteresis` | 8 | Degrees a previous direction sticks past its border |
| `confirm_frames` | 3 | Frames in a row before a new word |
| `back_confirm_frames` | 6 | Frames in a row before `back` |
| `dropout_hold_s` | 0.3 | Hand lost: hold the word this long, then `none` |
| `key_hold_s` | 0.8 | Keyboard mode: word lifetime after a key, above the usual 0.5 to 0.66 s key-repeat delay; 0 = latch |

`confirm_frames` counts camera frames, so the delay depends on the
webcam's frame rate: 3 frames is 0.1 s at 30 fps, 0.2 s at 15 fps.

## Tests

```bash
cd src/gesture_control
python -m pytest test
```

These cover the classifier (fist, thumb-out fist, each sector, deadzone,
hysteresis, rotation, frame aspect), the smoother (confirm frames, longer
`back`, dropout hold then `none`), the stale-word holder and the keyboard
mapping. They use synthetic landmarks, so no camera, ROS or MediaPipe.

## Files

```
gesture_control/
  classifier.py      landmarks -> word: fist, deadzone, angle sectors, hysteresis (no ROS)
  smoother.py        raw word per frame -> stable word (no ROS)
  command_source.py  LatestWord (stale -> none) and the classifier + smoother pipeline
  keyboard_source.py keyboard input mode
  hand_tracker.py    MediaPipe Tasks HandLandmarker, mp.solutions fallback
  camera_loop.py     webcam -> tracker -> pipeline loop, overlay drawing
  gesture_node.py    ROS 2 node (contract v0.3)
  webcam_demo.py     laptop demo without ROS
config/gesture.yaml
launch/gesture.launch.py
test/
```

## Credit

Ported from the hand-tracking notebook `python_camera.ipynb` in
[toonzzzrock/mini_project_arduino](https://github.com/toonzzzrock/mini_project_arduino)
(MIT License, Copyright (c) 2025 Pachara Wongthanakarn): mirrored webcam,
MediaPipe Hands with one hand, fist vs open hand, and the hand angle around
the frame centre. The UDP / ESP8266 / Arduino link is dropped, and the
continuous angle is replaced by the word sectors above.
