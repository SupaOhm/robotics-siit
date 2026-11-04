# Robot setup (Lane 1)

Bring-up checklist for the Yahboom RosmasterPi A1. It confirms the hardware
and software decisions in [decisions.md](decisions.md) (D16–D22). Fill in
the blanks as you go. Other lanes read the results from here.

## 1. OS and ROS 2 (D16)

- [ ] Board model (`cat /proc/device-tree/model`): `____`
- [ ] Yahboom image booted, ROS 2 Humble. Version / image name: `____`
- [ ] Desktop switched off (headless), reached over SSH
- [ ] Is ROS native or inside Docker? Container name and how to enter: `____`
- [ ] If Docker: container runs with `--network host` and has the mic,
      speaker and camera (`--device /dev/snd --device /dev/video0`)
- [ ] `ros2 doctor` runs without errors

## 2. Network (D17)

- [ ] Phone hotspot: auto-off disabled, phone on a charger
- [ ] Robot joins the hotspot. Hostname `____`, IP `____` (fixed if the
      phone allows it)
- [ ] Laptop joins the hotspot

Every machine, in `~/.bashrc`:

```bash
source /opt/ros/humble/setup.bash
export ROS_DOMAIN_ID=42
export ROS_LOCALHOST_ONLY=0
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp   # sudo apt install ros-humble-rmw-cyclonedds-cpp
```

- [ ] Robot: `ros2 run demo_nodes_cpp talker`; laptop: `ros2 run demo_nodes_cpp listener` gets the messages
- [ ] Same test the other way round
- [ ] If discovery fails on this phone (some iPhones block multicast): try
      another phone, or fall back to Fast DDS with a discovery server
- [ ] Gesture laptop OS (needs ROS 2 Humble: Ubuntu 22.04, WSL2, or Docker): `macOS on purin's M1 MacBook, ROS 2 Humble from RoboStack (tools/mac_ros_setup.sh)`

## 3. Hardware

| Device | Check | Result |
|---|---|---|
| Base | `ros2 topic pub --once /cmd_vel geometry_msgs/msg/Twist "{linear: {x: 0.1}}"` moves it, zero stops it | |
| Turn in place (D13) | `ros2 topic pub --once /cmd_vel geometry_msgs/msg/Twist "{angular: {z: 0.5}}"` rotates it on the spot (mecanum), `{}` stops it | |
| IMU (Lane 3) | During that turn, `ros2 topic echo /imu/data_raw --field angular_velocity.z` reads about +0.5: rad/s, positive turning left. `ros2 topic hz /imu/data_raw` well above 5 Hz | `____` |
| Base driver launch | Command that starts it | `____` |
| Camera (D21) | Topic name, `ros2 topic hz` rate, resolution. Sees a standing person's upper body at 0.3 m? | `____` |
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

```bash
git clone https://github.com/SupaOhm/robotics-siit.git ~/robotics-siit
cd ~/robotics-siit
colcon build --symlink-install
source install/setup.bash
```

- [ ] Builds on the robot
- [ ] `pip install` works for: `ultralytics` + `ncnn` (Lane 2), `vosk`,
      `python-telegram-bot` (Lane 4)

## 5. Hand-off

Update `docs/interfaces.md` with the real camera topic and sensor, mark
D16–D22 in `docs/decisions.md` as confirmed or changed, and tell Lane 3
(sensor) and Lane 5 (benchmark on the robot).
