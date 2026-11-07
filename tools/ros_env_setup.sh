#!/usr/bin/env bash
# ROS network settings for a Linux laptop (Ubuntu 22.04 or WSL2) with
# ROS 2 Humble installed. Sets the four ~/.bashrc lines from
# docs/robot-setup.md §2 (D16, D17) and installs CycloneDDS.
#
#   bash tools/ros_env_setup.sh          # set up, then print the check line
#   bash tools/ros_env_setup.sh check    # only print the check line
#
# Post the check line on the robot session issue. Re-running is safe.
# Mac: use tools/mac_ros_setup.sh instead.

set -eo pipefail

RC="$HOME/.bashrc"
PKG=ros-humble-rmw-cyclonedds-cpp

check() {
  bash -ic 'echo "$(hostname): ROS_DOMAIN_ID=$ROS_DOMAIN_ID ROS_LOCALHOST_ONLY=$ROS_LOCALHOST_ONLY RMW_IMPLEMENTATION=$RMW_IMPLEMENTATION"' 2>/dev/null
  if dpkg -s "$PKG" >/dev/null 2>&1; then echo "$PKG installed"; else echo "$PKG MISSING"; fi
}

if [ "$1" = check ]; then check; exit 0; fi

if [ ! -f /opt/ros/humble/setup.bash ]; then
  echo "ROS 2 Humble not found in /opt/ros/humble. Install it first." >&2
  exit 1
fi

dpkg -s "$PKG" >/dev/null 2>&1 || sudo apt-get install -y "$PKG"

# Drop old values (some images set domain 61), then append ours
touch "$RC"
[ -f "$RC.bak" ] || cp "$RC" "$RC.bak"   # keep the first, unedited backup on re-runs
TMP=$(mktemp)
cp "$RC" "$TMP"
grep -vE '^export (ROS_DOMAIN_ID|ROS_LOCALHOST_ONLY|RMW_IMPLEMENTATION)=' "$TMP" > "$RC" || true
rm -f "$TMP"
grep -qxF 'source /opt/ros/humble/setup.bash' "$RC" || echo 'source /opt/ros/humble/setup.bash' >> "$RC"
cat >> "$RC" <<'EOF'
export ROS_DOMAIN_ID=42
export ROS_LOCALHOST_ONLY=0
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
EOF

# The daemon keeps the old settings until it restarts
bash -ic 'ros2 daemon stop' >/dev/null 2>&1 || true

check
echo "Open a new terminal (or: source ~/.bashrc) to use the new settings."
