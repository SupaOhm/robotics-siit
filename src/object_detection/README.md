# object_detection

Lane 2. Runs YOLO when the state machine asks, and says what is in front of
the robot: a named object, a person, or an unknown obstacle.

## Topics

| Topic | Type | Direction | Meaning |
|---|---|---|---|
| `/detect/request` | `std_msgs/String` | in | Request id |
| `/camera/image_raw` | `sensor_msgs/Image` | in | Camera frames. Set by `image_topic` |
| `/detect/result` | `std_msgs/String` (JSON) | out | `{id, kind, label, confidence, clip}` with the request's id |

## Rules

- YOLO runs on the first frame after a request.
- Any `person` above `person_threshold` wins, whatever else is in frame.
- Otherwise the largest box is named, if it is in the name table and above
  `object_threshold`.
- Anything else is `unknown`, which plays `found_obstacle`.
- With no camera frame, or if YOLO fails, there is no reply. The state machine
  retries, then goes to `CHECKPOINT`.

## Setup

The model isn't in the repo. Export it once:

```bash
pip install "numpy==1.26.4" "opencv-python<4.12" ultralytics ncnn
mkdir -p ~/models && cd ~/models
yolo export model=yolo11n.pt format=ncnn imgsz=320
```

This creates `~/models/yolo11n_ncnn_model/`, which `model_path` points to, so
you can launch from any folder. If you exported it somewhere else before, move
that folder here.

`~` is the home folder of whoever runs the node. With `sudo` or in Docker, that
is a different folder, so the model has to be there too. If the model is
missing, the node stops at start-up and the error gives the path it tried.

Keep the NumPy pin. A plain `pip install ultralytics` installs NumPy 2, and
then `cv_bridge` on ROS 2 Humble fails to import, for every node that uses it.

## Run

```bash
ros2 launch object_detection detector.launch.py
```

To ask for a detection by hand:

```bash
ros2 topic pub --once /detect/request std_msgs/msg/String "{data: d1}"
ros2 topic echo /detect/result
```

## Adding an object

Add a line to `name_table` in `config/detector.yaml`, for example
`"potted plant=plant"`. Then ask Lane 4 for the `found_plant` clip.

## Tests

The rules are in plain Python, so the tests need no ROS or YOLO:

```bash
python -m pytest test
```
