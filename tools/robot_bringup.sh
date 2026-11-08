#!/bin/bash
# Start, stop or check every robot node, in order. Run on the Pi, not in the container:
#   bash ~/share/robotics-siit/tools/robot_bringup.sh start
#   bash ~/share/robotics-siit/tools/robot_bringup.sh status
#   bash ~/share/robotics-siit/tools/robot_bringup.sh stop
# Node logs: /tmp/bringup/<node>.log in the container.
set -u

C=eager_pascal
WS=/root/share/robotics-siit
LOGS=/tmp/bringup
YOLO=/root/share/yolo11n_ncnn_model
VOSK=/root/share/vosk-model-small-en-us-0.15

die() { echo "ERROR: $*" >&2; exit 1; }

# An interactive shell reads /root/.bashrc: the workspaces, domain 42 and ROBOT_PASSWORD_HASH.
# The sed drops the banner that .bashrc prints.
in_c() {
  docker exec "$C" bash -ic "$1" 2>/dev/null \
    | sed '/^-\{20,\}$/d; /ROS_DOMAIN_ID:/d; /my_robot_type:/d'
}

# start_node <name> <command>: runs detached, output to $LOGS/<name>.log
start_node() {
  echo "start  $1"
  docker exec -d "$C" bash -ic "mkdir -p $LOGS; exec $2 > $LOGS/$1.log 2>&1"
}

# wait_topic <topic> <seconds>: wait for one message. ros2 topic echo exits at
# once while the topic doesn't exist yet, so retry until the time is up.
wait_topic() {
  local end=$((SECONDS + $2))
  while [ $SECONDS -lt $end ]; do
    in_c "timeout 5 ros2 topic echo --once --no-arr $1 > /dev/null && echo got" | grep -q got \
      && { echo "ok     $1"; return; }
    sleep 1
  done
  die "no message on $1 after $2 s; see $LOGS/*.log in the container"
}

cmd_vel_publishers() {
  in_c "ros2 topic info /cmd_vel" | sed -n 's/^Publisher count: //p'
}

do_start() {
  docker ps --format '{{.Names}}' | grep -qx "$C" || docker start "$C" > /dev/null \
    || die "can't start $C"
  sleep 2
  [ -n "$(in_c 'ros2 node list' | grep -E '^/(state_machine|detector_node)$')" ] \
    && die "nodes already running; run stop first"

  # USB numbering changes between boots: link the LiDAR, never the motor board.
  lidar=$(readlink -f /dev/rplidar) || die "/dev/rplidar missing on the Pi"
  [ "$lidar" = "$(readlink -f /dev/myserial)" ] && die "/dev/rplidar and /dev/myserial are both $lidar"
  echo "LiDAR  $lidar"

  # The gamepad is a second /cmd_vel publisher; run_handle.sh starts it at every container start.
  in_c "ps -eo pid,args | grep -E '[y]ahboom_joy_M1|[j]oy_node' | awk '{print \$1}' | xargs -r kill"
  in_c "ln -sf $lidar /dev/rplidar"

  start_node lidar "ros2 launch ydlidar_ros2_driver ydlidar_launch.py"
  wait_topic /scan 20
  start_node avoidance "ros2 launch obstacle_avoidance avoidance.launch.py"
  wait_topic /obstacle/detected 15
  # The camera must publish before detector_node starts, or the detector gets no frames.
  start_node camera "ros2 run usb_cam usb_cam_node_exe --ros-args -p video_device:=/dev/video0 \
-p image_width:=640 -p image_height:=480 -p framerate:=15.0 -r image_raw:=/camera/image_raw"
  wait_topic /camera/image_raw 20
  start_node detector "ros2 run object_detection detector_node --ros-args \
--params-file $WS/install/object_detection/share/object_detection/config/detector.yaml \
-p model_path:=$YOLO"
  start_node audio "env ALSA_CARD=2 ros2 launch audio_player audio.launch.py"
  start_node password "ros2 launch password_system password.launch.py vosk_model_path:=$VOSK"
  start_node telegram "ros2 launch telegram_alert telegram.launch.py env_file:=$WS/.env"
  sleep 8
  # Last, so every module is up when it starts sending requests.
  start_node robot_core "ros2 launch robot_core robot_core.launch.py"
  wait_topic /robot/state 20
  do_status
}

do_status() {
  echo "--- nodes"
  in_c "ros2 node list"
  n=$(cmd_vel_publishers)
  echo "--- /cmd_vel publishers: ${n:-?} (want 1: state_machine)"
  [ "$n" = "1" ] || echo "WARNING: not exactly one /cmd_vel publisher"
}

OURS='ros2 launch (robot_cor[e]|telegram_aler[t]|password_syste[m]|audio_playe[r]|obstacle_avoidanc[e]|ydlidar_ros2_drive[r])|detector_nod[e]|usb_cam_node_ex[e]|camera_til[t]'

do_stop() {
  # state_machine first, so its final zero /cmd_vel is the last command the wheels get.
  in_c "pkill -INT -f 'ros2 launch robot_cor[e]'"
  sleep 3
  in_c "pkill -INT -f '$OURS'"
  for _ in $(seq 10); do
    [ -z "$(in_c "pgrep -f '$OURS'")" ] && { echo "stopped"; return; }
    sleep 1
  done
  echo "WARNING: still running after 13 s:"
  in_c "ps -eo pid,args | grep -E '$OURS' | cut -c1-100"
}

case "${1:-}" in
  start)  do_start ;;
  stop)   do_stop ;;
  status) do_status ;;
  *)      echo "usage: $0 start|stop|status" >&2; exit 2 ;;
esac
