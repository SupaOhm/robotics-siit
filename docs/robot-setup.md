# Robot setup (Lane 1)

Bring-up checklist for the Yahboom ROSMASTER M1. It confirms the hardware
and software decisions in [decisions.md](decisions.md) (D16–D22). Fill in
the blanks as you go. Other lanes read the results from here.

## 1. OS and ROS 2 (D16)

- [x] Board model (`cat /proc/device-tree/model`): `Raspberry Pi 5 Model B Rev 1.1, 8 GB` (#29)
- [x] Yahboom image booted, ROS 2 Humble. Version / image name: `Raspberry Pi OS (Debian 12 bookworm) on the host; ROS 2 Humble in the container, image 192.168.2.51:5000/ros-humble-m1:1.1.1`
- [x] Desktop switched off (headless), reached over SSH
- [x] Is ROS native or inside Docker? Container name and how to enter: `Docker, container eager_pascal: ssh pi@<robot IP>, then docker exec -it eager_pascal bash` (from the Pi, not inside the container)
      - The container's main process is `/root/run_handle.sh`. It sets the
        domain (line 13, now `ROS_DOMAIN_ID=42` and CycloneDDS) and starts the
        base driver and the gamepad node. Change the domain there, then
        `docker restart eager_pascal` on the Pi
      - Don't also launch `laser_bringup_launch.py`: two drivers on
        `/dev/myserial` both fail. Don't run `~/run_humble.sh` or
        `~/ros2_docker.sh` either: each makes a new container
      - The image's `/root/.bashrc` sets `ROS_DOMAIN_ID=61` on line 100; it is
        now 42, with `ROS_LOCALHOST_ONLY=0`, CycloneDDS and the workspace
        `install/setup.bash` added
      - Both edits live in the container. They survive a restart, not a
        re-created container
      - `/home/pi/share` on the Pi is `/root/share` in the container
      - The container has no `/dev/rplidar` (the LiDAR is `/dev/ttyUSB0`).
        Start the LiDAR with `ln -sf /dev/ttyUSB0 /dev/rplidar` then
        `ros2 launch ydlidar_ros2_driver ydlidar_launch.py`. The link goes
        when the container restarts
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
| Turn in place (D13) | `ros2 topic pub --once /cmd_vel geometry_msgs/msg/Twist "{angular: {z: 0.5}}"` rotates it on the spot (mecanum), `{}` stops it | Turns on the spot. Forward at 0.05 m/s doesn't move it, 0.15 m/s does. A running `state_machine` sends zero `/cmd_vel` at 10 Hz, so stop it before any manual test |
| IMU (Lane 3) | During that turn, `ros2 topic echo /imu/data_raw --field angular_velocity.z` reads about +0.5: rad/s, positive turning left. `ros2 topic hz /imu/data_raw` well above 5 Hz | `+0.40 rad/s for +0.5 (80%), 10 Hz, RELIABLE` |
| Base driver launch | Command that starts it | `ros2 launch yahboomcar_ctrl yahboomcar_joy_launch.py`, run by `/root/run_handle.sh` at container start. Starts `Mcnamu_driver_M1` and the gamepad node `yahboom_joy_M1`. **Stop the gamepad before the state machine runs**, or `/cmd_vel` has two publishers and the robot jerks or won't move. In the container: `ps aux \| grep -E 'yahboom_joy_M1\|joy_node'`, then `kill` those PIDs. Checked 6 Nov: `Mcnamu_driver_M1` (`/driver_node`) keeps running and `/cmd_vel` drops to 0 publishers; once the state machine runs it shows 1. Don't use `pkill -f` from a `bash -c` whose command line contains the names: it kills that shell too. If `state_machine` dies mid-drive without its final zero (Ctrl-C, 6 Nov), the wheels stop on their own. The gamepad comes back on every container restart; a lasting fix is for `run_handle.sh` to start the driver without the gamepad (not done yet) |
| Camera (D21) | Topic name, `ros2 topic hz` rate, resolution. A person stands where the robot stops, then at 0.3 m: does YOLO find `person` by legs or feet? Record each for Lane 2: `ros2 bag record -o person_front /camera/image_raw /cmd_vel` | Not started at boot. Started by hand: `ros2 run usb_cam usb_cam_node_exe --ros-args -p video_device:=/dev/video0 -p image_width:=640 -p image_height:=480 -p framerate:=15.0 -r image_raw:=/camera/image_raw`. Rate and the person test: `____` |
| Distance sensor (D19) | LiDAR fitted? Model, topic (`/scan`?), rate, which way 0° points, QoS (`ros2 topic info -v /scan`). Else ultrasonic topic | `YDLIDAR T-mini on /scan, 10 Hz, 404 beams over 360°, BEST_EFFORT. 0° points backward (a wall in front of the camera reads at 180°), so front_angle_deg: 180.0` |
| Low objects (Lanes 2, 3) | Height of the LiDAR beam above the floor. Anything lower never stops the robot, so it is never named. Once `obstacle_avoidance` runs (§4), put a cup, then a bottle, 0.3 m in front of the bumper: `ros2 topic echo /obstacle/distance` should read about 0.3 plus the LiDAR-to-bumper gap | Beam about 16 cm above the floor (Yahboom drawing: LiDAR top at 181.4 mm). A cup 0.3 m ahead: not seen. A clear Crystal bottle 0.3 m ahead: the beam went through it (read 0.60 m) |
| Size (Lane 3) | Robot width (`corridor_half_width` is half of it plus a margin) and the gap from the LiDAR to the front bumper | Yahboom drawing: 231.4 mm wide, 284.4 mm long, LiDAR about 15 cm behind the front bumper (purin, taped on 6 Nov, #40) |
| Stopping distance (Lane 3) | Once the state machine runs, drive at `linear_speed` toward a box and measure the gap left in front of the bumper. The robot keeps moving for up to about 0.45 s after the box comes within `stop_distance` (0.40 m from the LiDAR): about 9 cm at 0.2 m/s | `With the old 0.30: stopped about 30 cm from the LiDAR at 0.2 m/s, so about 15 cm from the bumper, by eye (purin, 6 Nov). stop_distance is now 0.40, about 25 cm from the bumper` |
| Microphone (D22) | `arecord -l` lists the USB mic; `arecord -d 3 t.wav && aplay t.wav` is clear | Sound card 2 (USB voice board); recording works. Set capture to 40% (`amixer -c 2 sset Mic capture 40%`): 100% (+23 dB) clipped. Open at 48 kHz (`mic_sample_rate: 48000`): at 44.1 kHz it delivers about 24,300 samples/s. 5 Nov at 40%: peak -0.2 to -7.3 dBFS, 0.00% clipped, room noise 110 to 210 ([mic-check-results-nov5.md](mic-check-results-nov5.md)) |
| Voice module | Free speech, or fixed command words only? | Used only as the mic and speaker (sound card 2). Vosk does the recognition: digits-only grammar for the check, free speech for the Telegram caption only (D24). Vosk streaming heard 10/10 digits (D34) |
| Speaker (D25) | `aplay` a test `.wav` is loud enough at 2 m | `____` |
| Internet | `ping api.telegram.org` works **inside the container** over the hotspot, not only on the Pi | 5 Nov: the Pi reached it but the container didn't, because its `/etc/resolv.conf` still pointed at `192.168.2.1` from an old network, so `pip` and Telegram failed. Set to the hotspot (`10.128.189.109`) and `8.8.8.8`; the old file is `/etc/resolv.conf.bak-192.168.2.1`. Check again on another phone |
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

Update later with `git pull` inside the container
(`cd /root/share/robotics-siit && git pull`), then `colcon build`. `git pull`
as `pi` on the Pi fails with "insufficient permission for adding an object to
repository database": the container runs git as root, so some `.git` objects
belong to root. To keep git on the Pi instead, run
`sudo chown -R pi:pi ~/share/robotics-siit` once.

- [x] Builds on the robot (7 packages, 10 s)
- [x] `pip install` works for: `ultralytics` + `ncnn` (Lane 2), `vosk`,
      `python-telegram-bot` (Lane 4). `ultralytics` and `ncnn` were already
      installed; added `vosk` 0.3.45. `python-telegram-bot` was missing
      (`ModuleNotFoundError`): guy installed 22.8, and `SpeechRecognition`.
      NumPy stays at 1.26.4

## 5. Hand-off

Update `docs/interfaces.md` with the real camera topic and sensor, mark
D16–D22 in `docs/decisions.md` as confirmed or changed, and tell Lane 3
(sensor) and Lane 5 (benchmark on the robot).
