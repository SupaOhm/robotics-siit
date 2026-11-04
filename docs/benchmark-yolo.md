# YOLO benchmark on the robot (Lane 5)

Phase 1 task for Lane 5: benchmark YOLO on the robot and lock the time limit
per frame. It answers the Lane 5 row under "Still open" in
[interfaces.md](interfaces.md) and the gesture FPS question in
[PLAN.md](../PLAN.md). Measured on Nov 4 with
[`tools/bench_vision.py`](../tools/bench_vision.py).

## Result on the robot

| Model (YOLO11n, 320 px) | One YOLO frame: mean / p95 / slowest | FPS | CPU temperature |
|---|---|---|---|
| **NCNN** | **28 / 66 / 213 ms** | 29.3 | 52 → 56 °C |
| PyTorch `.pt` | 149 / 161 / 169 ms | 6.7 | 52 → 53 °C |

The camera alone gives 33 FPS at 320x240. Each run was 20 s (587 NCNN frames,
135 `.pt` frames).

Only the base driver in the boot container was running. The LiDAR, the camera
node and our own nodes were not, so the robot will be busier in the demo. The
margin below covers that.

## Proposed decisions

- **Time limit per YOLO frame on the robot: 1.0 s, slowest frame included.**
  `CLASSIFY` waits 3 s and retries once. 1 s leaves room for waiting for the
  next camera frame, `cv_bridge` and DDS. The robot's slowest NCNN frame
  (213 ms) is under a quarter of the limit.
- **YOLO stays on the robot (D18).** No need to move it to the laptop.
- **Use the NCNN export (D20).** It is about 5 times faster than `.pt`. The
  detector's `detector.yaml` already points to it.
- **Gesture control: at least 10 FPS, 15 FPS target.** With
  `confirm_frames: 3`, a new word takes 0.3 s at 10 FPS and 0.2 s at 15 FPS
  (`back`, at 6 frames: 0.6 s and 0.4 s). On a Windows laptop webcam,
  MediaPipe hands takes about 20 ms per frame, about 50 FPS of compute, so the
  camera is the limit: 30 FPS in good light, about 16 in a dim room. Still to
  run on purin's Mac, which runs `gesture_node`.

## Setup used

| Item | Value |
|---|---|
| Robot | Yahboom ROSMASTER M1 (box and container both say M1), mecanum wheels |
| Board | Raspberry Pi 5 Model B Rev 1.1, 8 GB |
| Host OS | Raspberry Pi OS, Debian 12 (bookworm), kernel 6.12.25 |
| ROS | ROS 2 Humble inside the Yahboom container, image `ros-humble-m1:1.1.1`, network `host` |
| Python (container) | 3.10.12, with `ultralytics` and `ncnn` already installed, NumPy 1.26.4, OpenCV 4.11.0 |
| Camera | USB camera `05a3:9230`, `/dev/video0`, visible inside the container |
| Model | `yolo11n.pt`, exported with `yolo export model=yolo11n.pt format=ncnn imgsz=320` (Ultralytics 8.4.197) |

Found during the run, for [robot-setup.md](robot-setup.md) (Lane 1):

- The container starts at boot with `ROS_DOMAIN_ID=61`. The contract uses 42.
- `/home/pi/share` on the host is `/root/share` in the container, and it
  survives a reboot.
- The topics `/cmd_vel`, `/imu/data_raw` and `/voltage` are there. `/scan` and
  a camera topic appear only after their drivers are started.
- Sound card 2 is a USB audio device with capture and playback (the YB-MAB02
  voice board and its speaker). The default output is HDMI, so use
  `plughw:2,0`. Not checked yet: recording quality, and whether the container
  can open the sound card.

## Laptop reference

Windows laptop (AMD Ryzen 7 8845HS, CPU only, good light):

| Setting | Result |
|---|---|
| YOLO11n 320 px, NCNN | 21 ms per frame |
| YOLO11n 320 px, `.pt` | 38 ms per frame |
| YOLO11n 640 px, `.pt` | 68 ms per frame |
| MediaPipe + YOLO (`.pt`) on every frame, 640x480 | 11 FPS |
| MediaPipe on every frame + YOLO every 3rd frame, 640x480 | 20 FPS |

## How to run it again

The robot's container already has the libraries. Export the model on a
laptop, then copy the script and the model into the shared folder:

```bash
yolo export model=yolo11n.pt format=ncnn imgsz=320
scp -r tools/bench_vision.py yolo11n_ncnn_model pi@<robot-ip>:~/share/
```

On the robot (find the container name with `docker ps`):

```bash
docker exec <container> bash -ic 'cd /root/share && python3 bench_vision.py \
  --model yolo11n_ncnn_model --sizes 320x240 \
  --configs camera_only,yolo_only --seconds 20 --csv robot_ncnn.csv'
```

The script prints PASS when the slowest YOLO frame is under
`--yolo-limit-ms` (default 1000). `--fake` checks the script without a camera
or a model. The model files are not in the repo (CONTRIBUTING.md).
