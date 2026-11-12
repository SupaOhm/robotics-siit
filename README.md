# robotics-siit: AI gesture-controlled security robot

A Yahboom ROSMASTER M1 that the operator drives with hand gestures. It
stops at obstacles, names them in English, and checks people at a
spoken-password checkpoint, alerting the operator on Telegram when a
password fails.

- **Plan, lanes and timeline:** [PLAN.md](PLAN.md)
- **How to contribute:** [CONTRIBUTING.md](CONTRIBUTING.md)
- **ROS contract (topics, payloads, state machine):** [docs/interfaces.md](docs/interfaces.md)
- **Why it is built this way (D-numbers):** [docs/decisions.md](docs/decisions.md)
- **Robot bring-up checklist:** [docs/robot-setup.md](docs/robot-setup.md)
- **Glossary:** [CONTEXT.md](CONTEXT.md)

## Layout

This is a ROS 2 colcon workspace. Each module is its own `ament_python`
package under `src/`, created and owned by its lane.

```
src/
  robot_core/         Lane 1, state machine, the only /cmd_vel publisher (state_machine)
  gesture_control/    Lane 2, hand gestures on the laptop (gesture_node)
  object_detection/   Lane 2, YOLO object naming (detector_node)
  audio_player/       Lane 4, spoken clips (audio_node)
  password_system/    Lane 4, spoken password (password_node)
  telegram_alert/     Lane 4, operator alerts (telegram_node)
  obstacle_avoidance/ Lane 3, obstacle stop and turn-away (avoidance_node)
  ...                 other packages are added by their lanes
docs/                 interface contract, decisions, robot setup
sim/                  CoppeliaSim scenes (Lane 5)
external/             third-party source kept as git submodules (see below)
tools/                setup, demo and benchmark scripts (not ROS packages)
```

## External sources

| Path | Source | Licence | Used for |
|---|---|---|---|
| `external/mini_project_arduino` | [toonzzzrock/mini_project_arduino](https://github.com/toonzzzrock/mini_project_arduino) | MIT | Existing MediaPipe gesture code (`python_camera.ipynb`) that Lane 2 (purin) ports into `gesture_control` |

It is a git submodule pinned to one commit. Clone with
`git clone --recurse-submodules`, or run `git submodule update --init` in an
existing clone. It is not a ROS package: do not edit it here, copy what is
needed into `src/`.

## Build

On a machine with ROS 2 (the robot, or Ubuntu / Docker with ROS 2 Humble):

```bash
git clone https://github.com/SupaOhm/robotics-siit.git
cd robotics-siit
colcon build --symlink-install
source install/setup.bash
```

macOS has no official ROS 2 packages. On a Mac, `bash tools/mac_ros_setup.sh`
installs Humble from RoboStack (conda) and builds `gesture_control` (tested
on an M1). See [src/gesture_control/README.md](src/gesture_control/README.md).

## Dependencies

### Operator laptop (gesture control)

Tested on a Mac (M1) only. The Ubuntu steps are written but not tried.

| Need | Mac | Ubuntu 22.04 |
|---|---|---|
| ROS 2 Humble, colcon | `mac_ros_setup.sh` installs it from RoboStack into the conda env `ros_env` | apt, from the ROS docs |
| CycloneDDS, domain 42 | `mac_ros_setup.sh` stores them in `ros_env` | `bash tools/ros_env_setup.sh` |
| MediaPipe and OpenCV | `mac_ros_setup.sh` runs `pip install mediapipe`, keeping the env's NumPy | `pip install mediapipe` |
| Hand model | `mac_ros_setup.sh` downloads `~/models/hand_landmarker.task` | `wget`, see [src/gesture_control/README.md](src/gesture_control/README.md#laptop-setup-ubuntu-2204-ros-2-humble) |

OpenCV has no separate install: MediaPipe brings it as `opencv-contrib-python`.
Don't also install `opencv-python`, as both provide `cv2` and overwrite each
other.

Check:

```bash
bash tools/mac_ros_setup.sh           # re-run is safe; prints mediapipe, opencv and rclpy versions
bash tools/mac_ros_setup.sh check     # runs gesture_node 8 s, expects ~10 Hz on /gesture/command
bash tools/ros_env_setup.sh check     # Ubuntu: domain, RMW and whether CycloneDDS is installed
```

To try the gestures on a Mac without ROS, `bash tools/mac_gesture_demo.sh`
makes a venv in `.venv-gesture/`, installs MediaPipe, downloads the model and
opens the webcam demo.

### Robot

Already installed in `eager_pascal`. A re-created container from the stock
image loses them; reinstall from each package's README:

| Package | Needs |
|---|---|
| `object_detection` | `pip install "numpy==1.26.4" "opencv-python<4.12" ultralytics ncnn`, YOLO model exported to `/root/share/yolo11n_ncnn_model` |
| `password_system` | `apt install portaudio19-dev python3-pyaudio`, `pip install SpeechRecognition vosk`, Vosk model in `/root/share/vosk-model-small-en-us-0.15`, `ROBOT_PASSWORD_HASH` in `/root/.bashrc` |
| `telegram_alert` | `pip install python-telegram-bot` (22.8), `.env` at the clone root |

Keep NumPy below 2: Humble's `cv_bridge` fails to import with NumPy 2.

Check, in the container:

```bash
python3 -c "import numpy, cv2, ultralytics, ncnn, vosk, speech_recognition, pyaudio, telegram; print('numpy', numpy.__version__)"
```

### Tests

`pip install pytest python-telegram-bot`. Nothing else: tests run without
ROS, MediaPipe or YOLO.

## Run the robot

Gesture recognition runs on the operator's laptop; every other node runs on
the robot. Both join the same phone hotspot and use the same ROS settings:

```bash
export ROS_DOMAIN_ID=42
export ROS_LOCALHOST_ONLY=0
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
```

### What starts on its own

ROS runs in the Docker container `eager_pascal` on the Pi. When the Pi
powers on, its autostart runs `docker start eager_pascal` (the same container
every time, not a new one). The container's main process,
`/root/run_handle.sh`, sets domain 42 and CycloneDDS and starts the base
driver and the gamepad node. Its `/root/.bashrc` sets the same domain, sources
the workspaces and holds `ROBOT_PASSWORD_HASH`.

Nothing else starts at boot: the LiDAR, camera and project nodes are started
with `robot_bringup.sh` below. If ROS comes up on domain 61, a fresh container
was made from the stock image; see section 1 of
[docs/robot-setup.md](docs/robot-setup.md).

### 1. Start the robot

Power it on, wait for it to join the hotspot, then from the laptop:

```bash
ssh pi@<robot IP>
bash ~/share/robotics-siit/tools/robot_bringup.sh start    # about 40 s
```

`start` kills the gamepad (a second `/cmd_vel` publisher), links the LiDAR,
starts the LiDAR, obstacle avoidance, camera, detector, audio, password and
Telegram nodes, then the state machine last. It ends by listing the nodes and
fails unless `/cmd_vel` has exactly one publisher.

```bash
bash ~/share/robotics-siit/tools/robot_bringup.sh status   # nodes, /cmd_vel publishers
bash ~/share/robotics-siit/tools/robot_bringup.sh stop     # state machine first, then the rest
```

Logs are in `/tmp/bringup/<node>.log` in the container
(`docker exec -it eager_pascal bash`). If `start` reports no `/cmd_vel`
subscriber, the container started before the Pi joined the WiFi: run
`docker restart eager_pascal` on the Pi, then `start` again. Details:
[tools/README.md](tools/README.md#robot_bringupsh-lane-1).

The Telegram node reads `.env` at the root of the robot's clone
(`TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`); see
[src/telegram_alert/README.md](src/telegram_alert/README.md).

### 2. Start hand gestures on the laptop

On a Mac, once:

```bash
bash tools/mac_ros_setup.sh           # RoboStack Humble in conda env ros_env, domain 42, MediaPipe, hand model, build
bash tools/mac_ros_setup.sh check     # 8 s self-test: ~10 Hz on /gesture/command
```

Then, after `robot_bringup.sh start` finishes:

```bash
bash tools/mac_ros_setup.sh run       # webcam
bash tools/mac_ros_setup.sh keyboard  # no camera: w a s d, space stop
```

On Ubuntu 22.04 (not tested), set up the dependencies above, then:

```bash
colcon build --packages-select gesture_control
source install/setup.bash
ros2 launch gesture_control gesture.launch.py
```

Gestures: fist `stop`, open hand above the centre `forward`, below `back`,
left or right turns in place. No hand, or for 0.5 s no message, stops the
robot. The full table is in
[src/gesture_control/README.md](src/gesture_control/README.md#gestures).

To check the link from the laptop: `ros2 topic echo /robot/state`.

## Tests

Keep the logic in plain Python modules and keep the ROS node thin, as
`password_system` does. Then the tests run on any laptop without ROS:

```bash
cd src/<package>
python -m pytest test
```
