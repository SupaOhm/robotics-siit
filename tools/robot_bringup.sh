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

# wait_topic <topic> <seconds> [show]: wait for one message, and with "show"
# print its data field. ros2 topic echo exits at once while the topic doesn't
# exist yet, so retry until the time is up.
wait_topic() {
  local end=$((SECONDS + $2)) msg
  while [ $SECONDS -lt $end ]; do
    msg=$(in_c "timeout 5 ros2 topic echo --once --no-arr $1 && echo got")
    if grep -qx got <<< "$msg"; then
      echo "ok     $1"
      [ -n "${3:-}" ] && echo "       $(grep -m1 '^data:' <<< "$msg")"
      return
    fi
    sleep 1
  done
  die "no message on $1 after $2 s; see $LOGS/*.log in the container"
}

# wait_nodes <seconds> <node>...: wait until every node is in ros2 node list.
wait_nodes() {
  local secs=$1 end=$((SECONDS + $1)) list missing; shift; missing=$*
  while [ $SECONDS -lt $end ]; do
    list=$(in_c "timeout 5 ros2 node list")
    missing=$(for n in "$@"; do grep -qx "$n" <<< "$list" || echo "$n"; done)
    [ -z "$missing" ] && { echo "ok     $*"; return; }
    sleep 1
  done
  die "not up after $secs s:" $missing "; see $LOGS/*.log in the container"
}

cmd_vel_publishers() {
  in_c "timeout 5 ros2 topic info /cmd_vel" | sed -n 's/^Publisher count: //p'
}

# The base driver is the only /cmd_vel subscriber. If it started before the
# Pi joined the WiFi, nodes started later can't see it (9 Nov QA, finding 1),
# and the wheels would never get state_machine's commands.
wait_base_driver() {
  local end=$((SECONDS + $1))
  while [ $SECONDS -lt $end ]; do
    [ "$(in_c "timeout 5 ros2 topic info /cmd_vel" | sed -n 's/^Subscription count: //p')" -ge 1 ] 2>/dev/null \
      && { echo "ok     base driver (/cmd_vel subscriber)"; return; }
    sleep 1
  done
  die "no /cmd_vel subscriber after $1 s: the base driver isn't visible, maybe it started before the WiFi; run: docker restart $C, then start again"
}

# The gamepad is a second /cmd_vel publisher; run_handle.sh starts it at every container start.
kill_gamepad() {
  in_c "ps -eo pid,args | grep -E '[y]ahboom_joy_M1|[j]oy_node' | awk '{print \$1}' | xargs -r kill"
}

# Our launch files and our executables, so a node started by hand with ros2 run
# is caught too. The [x] keeps the pattern from matching the shell running pgrep.
OURS='ros2 launch (robot_cor[e]|telegram_aler[t]|password_syste[m]|audio_playe[r]|obstacle_avoidanc[e]|ydlidar_ros2_drive[r])|(^|[ /])(state_machin[e]|camera_til[t]|telegram_nod[e]|password_nod[e]|audio_nod[e]|avoidance_nod[e]|detector_nod[e]|usb_cam_node_ex[e]|ydlidar_ros2_driver_nod[e])( |$)'
SM='ros2 launch robot_cor[e]|(^|[ /])state_machin[e]( |$)'

do_start() {
  docker ps --format '{{.Names}}' | grep -qx "$C" || docker start "$C" > /dev/null \
    || die "can't start $C"
  sleep 2
  # Any of our nodes, not only the last ones: a failed start leaves the LiDAR
  # running, and a second driver on the same port fails.
  [ -n "$(in_c "pgrep -f '$OURS'")" ] && die "nodes already running; run stop first"

  # USB numbering changes between boots: link the LiDAR, never the motor board.
  # readlink -e fails on a missing path; -f would print it and succeed.
  lidar=$(readlink -e /dev/rplidar) || die "/dev/rplidar missing on the Pi"
  [ "$lidar" = "$(readlink -e /dev/myserial)" ] && die "/dev/rplidar and /dev/myserial are both $lidar"
  echo "LiDAR  $lidar"

  kill_gamepad
  wait_base_driver 20
  [ "$(in_c "ln -sf $lidar /dev/rplidar && test -e /dev/rplidar && echo ok")" = ok ] \
    || die "can't link /dev/rplidar to $lidar in $C"

  start_node lidar "ros2 launch ydlidar_ros2_driver ydlidar_launch.py"
  wait_topic /scan 20
  start_node avoidance "ros2 launch obstacle_avoidance avoidance.launch.py"
  # /obstacle/detected publishes from start-up even with no scans; distance
  # needs a valid reading, so it shows the LiDAR reaches the node.
  wait_topic /obstacle/distance 15 show
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
  wait_nodes 30 /detector_node /audio_node /password_node /telegram_node
  # On a cold start, run_handle.sh may start the gamepad after the first kill.
  kill_gamepad
  # Last, so every module is up when it starts sending requests.
  start_node robot_core "ros2 launch robot_core robot_core.launch.py"
  wait_topic /robot/state 20
  do_status
  [ "$(cmd_vel_publishers)" = "1" ] || die "/cmd_vel must have one publisher (state_machine); run stop"
}

do_status() {
  echo "--- nodes"
  in_c "ros2 node list"
  n=$(cmd_vel_publishers)
  echo "--- /cmd_vel publishers: ${n:-?} (want 1: state_machine)"
  [ "$n" = "1" ] || echo "WARNING: not exactly one /cmd_vel publisher"
}

do_stop() {
  local start=$SECONDS end
  # state_machine first, so its final zero /cmd_vel is the last command the wheels get.
  in_c "pkill -INT -f '$SM'"
  sleep 3
  in_c "pkill -INT -f '$OURS'"
  end=$((SECONDS + 10))
  while [ $SECONDS -lt $end ]; do
    [ -z "$(in_c "pgrep -f '$OURS'")" ] && { echo "stopped"; return; }
    sleep 1
  done
  # A node blocked in a read (the mic, say) can ignore SIGINT.
  echo "still running after $((SECONDS - start)) s, sending SIGKILL"
  in_c "pkill -KILL -f '$OURS'"
  sleep 1
  [ -z "$(in_c "pgrep -f '$OURS'")" ] && { echo "stopped"; return; }
  in_c "ps -eo pid,args | grep -E '$OURS' | cut -c1-100"
  die "still running after SIGKILL"
}

case "${1:-}" in
  start)  do_start ;;
  stop)   do_stop ;;
  status) do_status ;;
  *)      echo "usage: $0 start|stop|status" >&2; exit 2 ;;
esac
