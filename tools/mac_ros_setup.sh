#!/usr/bin/env bash
# ROS 2 Humble on a Mac (Apple silicon) with RoboStack, then build and run
# gesture_control. Untested on a real Mac so far: report what breaks.
#
#   bash tools/mac_ros_setup.sh           # set up (first time) and build
#   bash tools/mac_ros_setup.sh run       # run gesture_node (camera)
#   bash tools/mac_ros_setup.sh keyboard  # run gesture_node in keyboard mode
#   bash tools/mac_ros_setup.sh check     # run the node 8 s and confirm it publishes
#   bash tools/mac_ros_setup.sh shell     # print how to use the env in your own terminal
#
# What setup does:
#   1. installs Miniforge (conda) with Homebrew if no conda is found
#   2. creates the conda env "ros_env" with ROS 2 Humble (ros-base), CycloneDDS
#      and colcon, from the robostack-staging channel
#   3. stores ROS_DOMAIN_ID=42 and RMW_IMPLEMENTATION=rmw_cyclonedds_cpp in the env (D16, D17)
#   4. pip-installs mediapipe into the env, keeping the env's numpy version
#   5. downloads the hand model to ~/models/hand_landmarker.task (once)
#   6. colcon-builds gesture_control
#
# Re-running is safe: finished steps are skipped. Remove everything with:
#   conda env remove -n ros_env

set -eo pipefail   # no -u: conda and ROS activation scripts read unset variables

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_NAME="ros_env"
MODEL_DIR="$HOME/models"
MODEL="$MODEL_DIR/hand_landmarker.task"
MODEL_URL="https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/latest/hand_landmarker.task"

say() { printf '\n==> %s\n' "$*"; }
die() { printf '\nERROR: %s\n' "$*" >&2; exit 1; }

[ "$(uname -s)" = "Darwin" ] || die "this script is for macOS. On Ubuntu 22.04, follow src/gesture_control/README.md."

find_conda() {
  if command -v conda >/dev/null 2>&1; then command -v conda; return; fi
  for c in /opt/homebrew/Caskroom/miniforge/base/bin/conda \
           /usr/local/Caskroom/miniforge/base/bin/conda \
           "$HOME/miniforge3/bin/conda" "$HOME/mambaforge/bin/conda" \
           "$HOME/miniconda3/bin/conda" "$HOME/anaconda3/bin/conda"; do
    if [ -x "$c" ]; then echo "$c"; return; fi
  done
}

activate_env() {
  local conda_bin; conda_bin="$(find_conda)"
  [ -n "$conda_bin" ] || die "conda not found. Run: bash tools/mac_ros_setup.sh"
  eval "$("$conda_bin" shell.bash hook)"
  conda activate "$ENV_NAME" || die "env $ENV_NAME missing. Run: bash tools/mac_ros_setup.sh"
}

source_workspace() {
  [ -f "$REPO/install/setup.bash" ] || die "not built yet. Run: bash tools/mac_ros_setup.sh"
  # shellcheck disable=SC1091
  source "$REPO/install/setup.bash"
}

camera_note() {
  cat <<'EOF'
   First run: macOS asks to give your terminal camera access. If nothing is
   detected, allow it in System Settings > Privacy & Security > Camera, then
   quit and reopen the terminal. If macOS asks whether python may accept
   incoming network connections, allow it: ROS 2 needs that to reach the robot.
EOF
}

do_setup() {
  # 1. conda
  local conda_bin; conda_bin="$(find_conda)"
  if [ -z "$conda_bin" ]; then
    command -v brew >/dev/null 2>&1 || die "neither conda nor Homebrew found. Install Homebrew from https://brew.sh, then re-run."
    say "Installing Miniforge with Homebrew"
    brew install --cask miniforge
    conda_bin="$(find_conda)"
    [ -n "$conda_bin" ] || die "Miniforge installed but conda not found. Open a new terminal and re-run."
  fi
  say "Using conda at $conda_bin"
  eval "$("$conda_bin" shell.bash hook)"

  # 2. env
  if ! conda env list | awk '{print $1}' | grep -qx "$ENV_NAME"; then
    say "Creating env $ENV_NAME with ROS 2 Humble (this downloads ~1 GB, takes a while)"
    conda create -y -n "$ENV_NAME" -c conda-forge -c robostack-staging \
      ros-humble-ros-base ros-humble-rmw-cyclonedds-cpp \
      colcon-common-extensions compilers cmake pkg-config make ninja
  else
    say "Env $ENV_NAME already exists"
  fi
  conda activate "$ENV_NAME"
  conda config --env --add channels conda-forge
  conda config --env --add channels robostack-staging
  conda config --env --remove channels defaults >/dev/null 2>&1 || true

  # 3. team ROS settings, stored in the env so every activation gets them
  conda env config vars set ROS_DOMAIN_ID=42 RMW_IMPLEMENTATION=rmw_cyclonedds_cpp >/dev/null
  conda activate "$ENV_NAME"   # re-activate to apply the vars
  say "Python $(python --version 2>&1 | cut -d' ' -f2), ROS_DOMAIN_ID=$ROS_DOMAIN_ID, RMW=$RMW_IMPLEMENTATION"

  # 4. mediapipe
  if ! python -c "import mediapipe" >/dev/null 2>&1; then
    say "Installing mediapipe into $ENV_NAME"
    local np_pin=""
    if python -c "import numpy" >/dev/null 2>&1; then
      np_pin="numpy==$(python -c 'import numpy; print(numpy.__version__)')"
      echo "   keeping the env's $np_pin so ROS packages built against it keep working"
    fi
    # shellcheck disable=SC2086
    python -m pip install mediapipe $np_pin || die "pip could not install mediapipe for Python $(python --version 2>&1 | cut -d' ' -f2).
   MediaPipe may have no wheel for this Python. Report the error above."
  fi
  python - <<'EOF'
import cv2, mediapipe as mp, rclpy  # noqa: F401
print("   mediapipe", mp.__version__, "| opencv", cv2.__version__, "| rclpy ok")
try:
    from mediapipe.tasks.python import vision  # noqa: F401
    print("   MediaPipe Tasks API: available")
except Exception as e:
    print("   MediaPipe Tasks API: NOT available (%s); the node will try mp.solutions" % e)
EOF

  # 5. model
  if [ ! -s "$MODEL" ] || [ "$(wc -c < "$MODEL")" -lt 1000000 ]; then
    say "Downloading the hand model to $MODEL"
    mkdir -p "$MODEL_DIR"
    curl -fL --retry 3 -o "$MODEL.part" "$MODEL_URL" || die "download failed: $MODEL_URL"
    local size; size=$(wc -c < "$MODEL.part")
    [ "$size" -gt 1000000 ] || { rm -f "$MODEL.part"; die "downloaded file is only $size bytes, not a model"; }
    mv "$MODEL.part" "$MODEL"
  fi
  say "Model: $MODEL"

  # 6. build
  say "Building gesture_control"
  cd "$REPO"
  colcon build --symlink-install --packages-select gesture_control

  say "Setup done. Next:"
  cat <<'EOF'
   bash tools/mac_ros_setup.sh check     # 8 s self-test: does /gesture/command publish?
   bash tools/mac_ros_setup.sh run       # camera mode, ESC/Ctrl-C to stop
   bash tools/mac_ros_setup.sh keyboard  # w/a/s/d, space = stop, x = none
EOF
}

do_run() {
  activate_env; source_workspace
  say "gesture_node, camera mode (Ctrl-C stops). In another terminal: bash tools/mac_ros_setup.sh shell"
  camera_note
  exec ros2 run gesture_control gesture_node --ros-args -p input_mode:=camera -p model_path:="$MODEL" "$@"
}

do_keyboard() {
  activate_env; source_workspace
  say "gesture_node, keyboard mode: w forward, s back, a left, d right, space stop, x none (Ctrl-C stops)"
  exec ros2 run gesture_control gesture_node --ros-args -p input_mode:=keyboard "$@"
}

do_check() {
  activate_env; source_workspace
  say "Self-test: start gesture_node for 8 s and listen on /gesture/command"
  camera_note
  # Run the installed executable directly (not via ros2 run) so SIGINT reaches the node itself.
  local exe="$REPO/install/gesture_control/lib/gesture_control/gesture_node"
  [ -x "$exe" ] || die "missing $exe. Re-run: bash tools/mac_ros_setup.sh"
  "$exe" --ros-args -p model_path:="$MODEL" >"$REPO/log/mac_check_node.log" 2>&1 &
  local node_pid=$!
  sleep 3
  ros2 topic echo /gesture/command std_msgs/msg/String >"$REPO/log/mac_check_echo.log" 2>&1 &
  local echo_pid=$!
  sleep 5
  kill -INT "$echo_pid" "$node_pid" 2>/dev/null || true
  sleep 1
  kill "$echo_pid" "$node_pid" 2>/dev/null || true
  wait "$node_pid" 2>/dev/null || true
  local count; count=$(grep -c '^data:' "$REPO/log/mac_check_echo.log" || true)
  echo "   messages heard in 5 s: $count (expect about 50 at 10 Hz)"
  echo "   words heard: $(grep '^data:' "$REPO/log/mac_check_echo.log" | sort | uniq -c | tr '\n' ' ')"
  if [ "${count:-0}" -ge 30 ]; then
    say "PASS: the node publishes at about 10 Hz"
  else
    say "FAIL: too few messages. Node log: $REPO/log/mac_check_node.log"
    tail -n 20 "$REPO/log/mac_check_node.log" || true
    exit 1
  fi
}

do_shell() {
  local conda_bin; conda_bin="$(find_conda)"
  cat <<EOF
Paste this into a terminal (zsh) to use ROS 2 there, e.g. for ros2 topic hz:

  eval "\$("${conda_bin:-conda}" shell.zsh hook)"
  conda activate $ENV_NAME
  source "$REPO/install/setup.zsh"
  ros2 topic hz /gesture/command
EOF
}

mkdir -p "$REPO/log"
cmd="${1:-setup}"; [ $# -gt 0 ] && shift
case "$cmd" in
  setup)    do_setup ;;
  run)      do_run "$@" ;;
  keyboard) do_keyboard "$@" ;;
  check)    do_check ;;
  shell)    do_shell ;;
  *) die "unknown command: $cmd (setup | run | keyboard | check | shell)" ;;
esac
