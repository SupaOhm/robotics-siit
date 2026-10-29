# password_system (Lane 4, password verification)

When the robot finds a person, that person must show a secret **hand-gesture
sequence**: a run of finger counts. The demo password is **1 - 3 - 5 - 2**.
They get **3 attempts**. After 3 failures the node reports `denied`, and the
main state machine starts the alert and Telegram flow.

ROS 2 (`ament_python`) package. The core logic is plain Python, so it can be
tested and tried without ROS.

## How a person enters the password

| Gesture | Meaning |
|---|---|
| Hold up 1-5 fingers for **0.8 s** | Enter that digit |
| Fist, or hand out of view, for **0.4 s** | Release (needed only to repeat the same digit, e.g. 2-2) |
| Change straight to a different count | The next digit (no release needed) |

- A full sequence of the wrong digits costs one attempt, and input starts over.
- No input for **15 s** also costs one attempt (the person froze or walked off).
- Finger counting uses distances from the wrist, so it works with either hand
  and with the hand tilted.

## Interface (for the main state machine, audio, and Telegram)

All messages are standard `std_msgs`, so there is no custom message package.

| Topic | Type | Direction | Meaning |
|---|---|---|---|
| `/password/start` | `std_msgs/Empty` | in | Person detected: start a session (resets attempts) |
| `/password/cancel` | `std_msgs/Empty` | in | Abort the session (e.g. person left) |
| `/password/result` | `std_msgs/String` | out | Exactly one per session: `granted`, `denied` (3 fails, so send the alert), or `cancelled` |
| `/password/event` | `std_msgs/String` (JSON) | out | Progress, for audio prompts and UI |
| `/password/token` | `std_msgs/String` | in | Inject one digit directly (simulation / testing) |
| `/camera/image_raw` | `sensor_msgs/Image` | in | Camera frames (`input_mode: camera`) |
| `/gesture/fingers` | `std_msgs/Int32` | in | Raw finger count per frame, `-1` = no hand (`input_mode: fingers_topic`) |

Event JSON: `{"type": ..., "attempts_left": 2, "tokens_entered": 1, "password_length": 4}`

| `type` | Suggested audio (P6) |
|---|---|
| `started` | Password prompt clip |
| `token` | Short beep (one digit accepted) |
| `wrong` / `attempt_timeout` | "Wrong password, try again" |
| `granted` | "Verified" / "access granted" |
| `locked_out` | Alert sound (the state machine also gets `denied` on `/password/result`) |
| `cancelled` | None |

Digit values are never published or logged, only how many have been entered.

Expected use by the main state machine:

```
person detected  -> publish /password/start
/password/result == "granted"   -> confirm out loud, mark safe, pass
/password/result == "denied"    -> alert sound + Telegram photo with Allow/Deny
person gone                     -> publish /password/cancel
```

## Build and run

```bash
cd <workspace>            # the repo root, which holds src/
colcon build --packages-select password_system
source install/setup.bash

# On the robot (MediaPipe runs here, only while a session is active)
ros2 launch password_system password.launch.py image_topic:=/camera/image_raw

# Simulation / no camera: send digits by hand
ros2 launch password_system password.launch.py input_mode:=topic_only
ros2 topic pub --once /password/start std_msgs/msg/Empty
ros2 topic pub --once /password/token std_msgs/msg/String "{data: '1'}"   # repeat for 3, 5, 2
ros2 topic echo /password/result
```

Camera mode needs `pip install mediapipe` on the robot (plus `cv_bridge` and
OpenCV from ROS). Check the Yahboom camera topic name with `ros2 topic list`
and pass it as `image_topic`.

If the gesture node (Lane 2) already runs MediaPipe Hands, it can publish
raw finger counts on `/gesture/fingers`. Set `input_mode: fingers_topic` so
MediaPipe isn't run twice, which helps the FPS budget.

### Change the password

```bash
ros2 run password_system make_password_hash 2413
```

Paste the printed `password_length`, `salt` and `password_hash` into
[config/password.yaml](config/password.yaml). Only a salted SHA-256 is stored,
so the code isn't readable in the repo. With 5 digit values the keyspace is
small (625 codes for length 4), so this is a checkpoint demo, not real
security. The 3-attempt limit is what protects it.

### Try it on a laptop webcam (no ROS)

```bash
pip install opencv-python mediapipe
cd src/password_system
python -m password_system.webcam_demo --password 1352
```

Press `s` to start a session and `q` to quit. The overlay shows the live
finger count, a hold progress bar, and `*` for each digit entered.

## Tests

```bash
cd src/password_system
python -m pytest test
```

These cover the verifier (grant, 3-strike lockout, timeouts, cancel), the
debouncer (hold, release, dropouts), and the finger counter (0-5 fingers,
rotated hands), using synthetic landmarks. No camera is needed.

## Tuning

| Parameter | Default | Raise it if... |
|---|---|---|
| `hold_time` | 0.8 s | Digits register by accident |
| `release_time` | 0.4 s | A flicker counts as a release |
| `input_timeout` | 15 s | People need more time per attempt |
| `FINGER_RATIO` / `THUMB_RATIO` in `finger_counter.py` | 1.15 / 1.2 | Curled fingers or a tucked thumb get counted |
| `process_every_n_frames` | 1 | The CPU is overloaded (2 = every other frame) |

## Files

```
password_system/
  verifier.py        attempt and timeout state machine (no ROS)
  gesture_input.py   finger count stream -> accepted digits (hold / release)
  finger_counter.py  MediaPipe landmarks -> finger count
  password_node.py   ROS 2 node wiring the above to topics
  hash_tool.py       make_password_hash CLI
  webcam_demo.py     laptop demo without ROS
config/password.yaml
launch/password.launch.py
test/
```
