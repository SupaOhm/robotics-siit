# Robot setup (Lane 1)

Bring-up checklist for the Yahboom RosmasterPi A1. It confirms the hardware
and software decisions in [decisions.md](decisions.md) (D16–D22). Fill in
the blanks as you go. Other lanes read the results from here.

## 1. OS and ROS 2 (D16)

- [x] Board model (`cat /proc/device-tree/model`): `Raspberry Pi 5 Model B Rev 1.1, 8 GB` (#29)
- [x] Yahboom image booted, ROS 2 Humble. Version / image name: `Raspberry Pi OS (Debian 12 bookworm) on the host; ROS 2 Humble in the container, image 192.168.2.51:5000/ros-humble-m1:1.1.1`
- [x] Desktop switched off (headless), reached over SSH
- [x] Is ROS native or inside Docker? Container name and how to enter: `Docker, container eager_pascal: docker exec -it eager_pascal bash` (from the Pi, not inside the container)
      - The container's main process is `/root/run_handle.sh`. It sets the
        domain (line 13, now `ROS_DOMAIN_ID=42` and CycloneDDS) and starts the
        base driver. Change the domain there, then `docker restart eager_pascal`
        on the Pi
      - The image's `/root/.bashrc` sets `ROS_DOMAIN_ID=61` on line 100; it is
        now 42, with `ROS_LOCALHOST_ONLY=0`, CycloneDDS and the workspace
        `install/setup.bash` added
      - Both edits live in the container. They survive a restart, not a
        re-created container
      - `/home/pi/share` on the Pi is `/root/share` in the container
- [x] If Docker: container runs with `--network host` and has the mic,
      speaker and camera (`--device /dev/snd --device /dev/video0`): both
      visible in the container; sound card 2 (USB voice board) has capture
      and playback
- [x] `ros2 doctor` runs without errors

## 2. Network (D17)

- [x] Phone hotspot: auto-off disabled, phone on a charger
- [x] Robot joins the hotspot. Hostname `raspberrypi`, IP `10.128.189.11` on `wlan0` (fixed if the
      phone allows it)
- [x] Laptop joins the hotspot

Every machine, in `~/.bashrc`. On a Linux laptop, `bash tools/ros_env_setup.sh`
writes these lines and installs CycloneDDS; `bash tools/ros_env_setup.sh check`
prints the line to post on the session issue. On a Mac, `tools/mac_ros_setup.sh`
sets them in the `ros_env` conda environment.

```bash
source /opt/ros/humble/setup.bash
export ROS_DOMAIN_ID=42
export ROS_LOCALHOST_ONLY=0
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp   # sudo apt install ros-humble-rmw-cyclonedds-cpp
```

- [x] Robot: `ros2 run demo_nodes_cpp talker`; laptop: `ros2 run demo_nodes_cpp listener` gets the messages
- [x] Same test the other way round
- [x] If discovery fails on this phone (some iPhones block multicast): try
      another phone, or fall back to Fast DDS with a discovery server. Not
      needed: discovery works with CycloneDDS
- [ ] Gesture laptop OS (needs ROS 2 Humble: Ubuntu 22.04, WSL2, or Docker): `macOS on purin's M1 MacBook, ROS 2 Humble from RoboStack (tools/mac_ros_setup.sh)`

## 3. Hardware

`python3 tools/lane3_bringup_check.py` runs the Lane 3 rows (turn in place,
IMU, distance sensor, low objects) and prints results to paste here. Stop the
state machine first: the script sends its own turn on `/cmd_vel`.

| Device | Check | Result |
|---|---|---|
| Base | `ros2 topic pub --once /cmd_vel geometry_msgs/msg/Twist "{linear: {x: 0.1}}"` moves it, zero stops it | Works on domain 42 (5 Nov) |
| Turn in place (D13) | `ros2 topic pub --once /cmd_vel geometry_msgs/msg/Twist "{angular: {z: 0.5}}"` rotates it on the spot (mecanum), `{}` stops it | |
| IMU (Lane 3) | During that turn, `ros2 topic echo /imu/data_raw --field angular_velocity.z` reads about +0.5: rad/s, positive turning left. `ros2 topic hz /imu/data_raw` well above 5 Hz | `____` |
| Base driver launch | Command that starts it | `ros2 launch yahboomcar_ctrl yahboomcar_joy_launch.py`, run by `/root/run_handle.sh` at container start. Starts `Mcnamu_driver_M1` and the gamepad node `yahboom_joy_M1`, which can also publish `/cmd_vel` |
| Camera (D21) | Topic name, `ros2 topic hz` rate, resolution. A person stands where the robot stops, then at 0.3 m: does YOLO find `person` by legs or feet? Record each for Lane 2: `ros2 bag record -o person_front /camera/image_raw /cmd_vel` | Not started at boot. Started by hand: `ros2 run usb_cam usb_cam_node_exe --ros-args -p video_device:=/dev/video0 -p image_width:=640 -p image_height:=480 -p framerate:=15.0 -r image_raw:=/camera/image_raw`. Rate and the person test: `____` |
| Distance sensor (D19) | LiDAR fitted? Model, topic (`/scan`?), rate, which way 0° points, QoS (`ros2 topic info -v /scan`). Else ultrasonic topic | `____` |
| Low objects (Lanes 2, 3) | Height of the LiDAR beam above the floor. Anything lower never stops the robot, so it is never named. Once `obstacle_avoidance` runs (§4), put a cup, then a bottle, 0.3 m in front: `ros2 topic echo /obstacle/distance` should read about 0.3 | `____` |
| Size (Lane 3) | Robot width (`corridor_half_width` is half of it plus a margin) and the gap from the LiDAR to the front bumper | `____` |
| Stopping distance (Lane 3) | Once the state machine runs, drive at `linear_speed` toward a box and measure the gap left in front of the bumper. The robot keeps moving for up to about 0.45 s after the box comes within 0.30 m of the LiDAR: about 13 cm at 0.3 m/s | `____` |
| Microphone (D22) | `arecord -l` lists the USB mic; `arecord -d 3 t.wav && aplay t.wav` is clear | `____` |
| Voice module | Free speech, or fixed command words only? | `____` |
| Speaker (D25) | `aplay` a test `.wav` is loud enough at 2 m | `____` |
| Internet | `ping api.telegram.org` works over the hotspot | |
| Battery | Minutes of driving on a full charge | `____` |

## 4. Repo on the robot

Clone on the Pi into the shared folder, build inside the container:

```bash
cd ~/share && git clone https://github.com/SupaOhm/robotics-siit.git   # on the Pi
docker exec -it eager_pascal bash
cd /root/share/robotics-siit
colcon build --symlink-install
source install/setup.bash
```

Update later with `git pull` on the Pi, then `colcon build` in the container.

- [x] Builds on the robot (7 packages, 10 s)
- [x] `pip install` works for: `ultralytics` + `ncnn` (Lane 2), `vosk`,
      `python-telegram-bot` (Lane 4). `ultralytics`, `ncnn` and
      `python-telegram-bot` 22.8 were already installed; added `vosk` 0.3.45.
      NumPy stays at 1.26.4

## 5. Hand-off

Update `docs/interfaces.md` with the real camera topic and sensor, mark
D16–D22 in `docs/decisions.md` as confirmed or changed, and tell Lane 3
(sensor) and Lane 5 (benchmark on the robot).
