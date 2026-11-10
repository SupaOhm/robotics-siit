# tools

Scripts that sit outside the ROS packages. Each tool has a section below that
names its lane; add one for yours.

## extract_boxes.py (Lane 2, ohm)

Runs the object detector (`src/object_detection`) on a laptop, on
phone photos or on recordings from the robot's camera. YOLO runs once and the
boxes go to a JSON file in `src/object_detection/test/`. The tests then apply
the rules with the thresholds in `config/detector.yaml`, so you can tune a
threshold and rerun `pytest` without the robot.

### Setup

Once, in a virtual environment on the laptop. No ROS is needed:

```bash
pip install ultralytics ncnn rosbags pillow pillow-heif
```

Export the model to `~/models` as in Setup in
`src/object_detection/README.md`, or pass `--model <folder>`.

### Where files go

Photos and recordings show people, so they stay off GitHub in `local/`, which
git ignores. Make one folder per session and give it any name you like, for
example `2026-11-04_bkd1101` or `demo_room`:

```
local/photos/<session>/originals/    photos as taken (HEIC, JPG...)
local/bags/<session>/recordings/     one ros2 bag folder per recording
```

Name each photo or recording `<expected>_<note>`, for example `chair_front`,
`person_side` or `obstacle_desk`. The expected answer is a spoken label from
the name table, `person`, or `obstacle` for something the robot can't name.

### Recording on the robot

```bash
ros2 bag record -o chair_front /camera/image_raw /cmd_vel
```

Drive at the object and stop where avoidance would stop the robot, 0.40 m
from the bumper. Stop with the teleop stop key, not by letting go of the keys, so
`/cmd_vel` records the stop. Keep recording for 5 s, then press Ctrl+C. The robot asks the detector
the moment it stops, so the tool uses frames from the moment `/cmd_vel` goes
to zero, one every 0.5 s.

### Running it

From the repo root, with your session's folder name:

```bash
python tools/extract_boxes.py local/bags/<session> \
    src/object_detection/test/robot_frames.json
python tools/extract_boxes.py local/photos/<session> \
    src/object_detection/test/floor_photos.json
```

It prints one line per photo or recording and saves copies with the boxes
drawn to `annotated/` in the session folder. Then run the tests:

```bash
cd src/object_detection && python -m pytest test
```

- **A photo passes** if the robot's answer matches the expected one.
- **A person recording passes** only if every frame says person, because a
  missed person skips the password.
- **Any other recording passes** if at least 80% of frames are right.

Entries already in the JSON keep their `expect` and `known_miss`, and only
their boxes are replaced. If a failure is understood and accepted, add
`"known_miss": "<reason>"` to its entry; the test then expects it to fail.

## lane3_bringup_check.py (Lane 3)

Runs Lane 3's hardware checks on the robot in one command, and prints a
summary to paste into section 3 of `docs/robot-setup.md`.

Run it on the robot with the base driver and the LiDAR running. Stop the state
machine first: the turn test publishes `/cmd_vel` itself.

```bash
source /opt/ros/humble/setup.bash
python3 tools/lane3_bringup_check.py
```

It checks:

1. `/scan` and `/imu/data_raw` arrive, and at what rate and QoS.
2. A box 0.3 m in front: which way the LiDAR's 0 degrees points, and what
   `obstacle_avoidance` would read.
3. A cup, then a bottle, 0.3 m in front: whether the LiDAR sees them.
4. A 2 s turn in place at +0.5 rad/s: whether the IMU reads about +0.5 rad/s.

`--no-objects` skips 2 and 3, and `--no-turn` skips 4. `--help` lists the
rest.

## sim_avoidance.py (Lane 3)

Runs `obstacle_avoidance` in CoppeliaSim, without ROS, on the course's Lab 03
robot. Details are in "Try it in CoppeliaSim" in
`src/obstacle_avoidance/README.md`.

```bash
pip install coppeliasim-zmqremoteapi-client
# open CoppeliaSim first, then:
python tools/sim_avoidance.py <path to Lab3_scene.ttt>
```

The lab scene isn't in the repo.

- Where to get it: TODO (Lane 3)
- CoppeliaSim version tested: TODO (Lane 3)

Nothing is saved. Don't save over the lab scene in CoppeliaSim afterwards.

## mac_gesture_demo.sh (Lane 2, purin)

Runs the `gesture_control` webcam demo on a Mac, without ROS. It finds Python
3.10 to 3.12, makes a venv in `.venv-gesture/`, installs MediaPipe, downloads
the hand model to `~/models/hand_landmarker.task` and starts the demo. Re-running
skips the steps already done.

```bash
bash tools/mac_gesture_demo.sh                       # set up (first time) and run
bash tools/mac_gesture_demo.sh --setup-only          # set up only
bash tools/mac_gesture_demo.sh --camera-name iPhone  # options pass to webcam_demo
```

ESC or q quits. On the first run, macOS asks to give your terminal camera
access. Details are in "Try it without ROS" in `src/gesture_control/README.md`.

## mac_ros_setup.sh (Lane 2, purin)

Installs ROS 2 Humble on a Mac from RoboStack (conda), into a conda env called
`ros_env`, and builds `gesture_control`. It also sets `ROS_DOMAIN_ID=42` and
CycloneDDS, installs MediaPipe and downloads the hand model.

```bash
bash tools/mac_ros_setup.sh           # set up and build (first time)
bash tools/mac_ros_setup.sh check     # run gesture_node 8 s and confirm it publishes
bash tools/mac_ros_setup.sh run       # gesture_node with the camera
bash tools/mac_ros_setup.sh keyboard  # gesture_node in keyboard mode
bash tools/mac_ros_setup.sh shell     # how to use the env in your own terminal
```

Remove it all with `conda env remove -n ros_env`. Details are in "On a Mac
(RoboStack)" in `src/gesture_control/README.md`.

- Tested on a real Mac: TODO (purin)
