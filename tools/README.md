# tools

Scripts that sit outside the ROS packages. Each tool has a section below that
names its lane; add one for yours.

## extract_boxes.py (Lane 2)

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

Drive at the object and stop where avoidance would stop the robot, 0.30 m
away. Stop with the teleop stop key, not by letting go of the keys, so
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
