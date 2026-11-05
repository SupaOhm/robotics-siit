# Lane 5 — CoppeliaSim & ROS 2 Simulation QA

This folder contains the ROS 2 simulation bridges and QA tools for the SIIT robotics project.

## 1. Scope

Tested integration:

CoppeliaSim SickS300 -> scan_bridge.py -> /scan -> Lane 3 avoidance_node -> /avoidance/cmd_vel -> qa_relay.py -> /cmd_vel -> sim_bridge.py -> CoppeliaSim youBot.

The QA relay is temporary and must not replace the Lane 1 state machine in the integrated robot.

This is a simulation of a KUKA youBot, not the physical Yahboom RosmasterPi A1.

## 2. Requirements

- Windows with Docker Desktop
- CoppeliaSim Edu 4.10
- Python with coppeliasim-zmqremoteapi-client for host-side inspection
- Docker image built from this folder's Dockerfile
- ROS 2 Humble (inside Docker)
- CoppeliaSim ZeroMQ Remote API on port 23000

ROS configuration:
- ROS_DOMAIN_ID=42
- RMW_IMPLEMENTATION=rmw_cyclonedds_cpp

Run all PowerShell commands from the repository root unless stated otherwise.

## 3. Files

- sim/lane5_obstacle_qa.ttt: saved CoppeliaSim obstacle test scene
- tools/lane5_sim/Dockerfile: ROS 2 environment
- tools/lane5_sim/sim_bridge.py: /cmd_vel to simulated wheels
- tools/lane5_sim/scan_bridge.py: simulated LiDAR to /scan
- tools/lane5_sim/qa_relay.py: temporary avoidance command relay
- tools/lane5_sim/qa_cancel_test.py: automated cancellation QA

The scene has been saved with an obstacle in front of the robot. Independent reopen-and-retest verification is still pending.

## 4. Build the Docker image

From the repository root:

```powershell
docker build -t lane5-ros-sim .\tools\lane5_sim
```

## 5. Start CoppeliaSim

Open:

sim/lane5_obstacle_qa.ttt

Start the simulation using the Play button.

The youBot driving script must not conflict with external wheel commands. The SickS300 sensor script must remain enabled.

## 6. Start the simulation bridge

PowerShell window 1:

```powershell
$simDir = (Resolve-Path ".\tools\lane5_sim").Path

docker run --rm -it --name lane5-bridge `
  -v "${simDir}:/workspace" `
  -w /workspace `
  lane5-ros-sim `
  bash -lc "source /opt/ros/humble/setup.bash && python3 sim_bridge.py"
```

The bridge subscribes to /cmd_vel and uses a 1-second command watchdog.

IMPORTANT: the container uses --rm. Files built only inside the container disappear when it is removed.

## 7. Start the LiDAR bridge

PowerShell window 2:

```powershell
docker exec -it lane5-bridge bash -lc "source /opt/ros/humble/setup.bash && python3 /workspace/scan_bridge.py"
```

Expected:
- /scan: sensor_msgs/msg/LaserScan
- 271 beams from -135 to +135 degrees
- Approximately 5 Hz

Check from another PowerShell window:

```powershell
docker exec lane5-bridge bash -lc "source /opt/ros/humble/setup.bash && timeout 8s ros2 topic hz /scan"
```

## 8. Install the Lane 3 package for QA

The tested Lane 3 code is from PR #3:
https://github.com/SupaOhm/robotics-siit/pull/3

Tested commit: 41e865b

Lane 3 was not merged into main at the time of this handoff.

One setup approach is to create a separate Git worktree:

```powershell
git fetch origin lane3/obstacle-avoidance
git worktree add --detach ..\lane3-qa FETCH_HEAD

docker exec lane5-bridge mkdir -p /ros_ws/src
docker cp "..\lane3-qa\src\obstacle_avoidance" lane5-bridge:/ros_ws/src/

docker exec -w /ros_ws lane5-bridge bash -lc "source /opt/ros/humble/setup.bash && colcon build --packages-select obstacle_avoidance"
```

These are reproducibility instructions; the worktree setup itself has not yet been rerun from a clean environment.

PowerShell window 4:

```powershell
docker exec -it -w /ros_ws lane5-bridge bash -lc "source /opt/ros/humble/setup.bash && source install/setup.bash && ros2 run obstacle_avoidance avoidance_node"
```

## 9. Run the temporary QA relay

Only for standalone Lane 3 QA, without the Lane 1 state machine.

PowerShell window 5:

```powershell
docker exec -it lane5-bridge bash -lc "source /opt/ros/humble/setup.bash && python3 /workspace/qa_relay.py"
```

The relay forwards /avoidance/cmd_vel to /cmd_vel with zero linear velocity and a 0.5-second watchdog.

Never run competing /cmd_vel publishers unintentionally.

## 10. Observe test results

PowerShell window 6:

```powershell
docker exec lane5-bridge bash -lc "source /opt/ros/humble/setup.bash && ros2 topic echo /avoidance/result"
```

Possible results:
- done
- cancelled
- failed

## 11. QA test cases

### QA-01: Obstacle detection

Place the Cuboid in front of the robot, then inspect:

```powershell
docker exec lane5-bridge bash -lc "source /opt/ros/humble/setup.bash && timeout 5s ros2 topic echo /obstacle/detected"
```

Expected: true while blocked.

Previously observed: approximately 0.287 m -> true, 0.45 m -> false.

### QA-02: Normal avoidance

Start CoppeliaSim, Lane 3 and the QA relay. Confirm the obstacle is detected.

```powershell
docker exec lane5-bridge bash -lc "source /opt/ros/humble/setup.bash && ros2 topic pub --once /avoidance/start std_msgs/msg/Empty '{}'"
```

Expected: robot rotates, clears the forward path and reports done.

Observed: 3 successful runs.

### QA-03: Cancel during avoidance

With Lane 3 and QA relay running:

```powershell
docker exec -it lane5-bridge bash -lc "source /opt/ros/humble/setup.bash && python3 /workspace/qa_cancel_test.py"
```

The script waits until a turning command is observed, then requests cancellation about 0.35 seconds later.

Expected: cancelled.

Observed: cancelled. The measured heading change during a 1-second post-cancellation interval was 0.01 degrees.

This does not establish the exact cancellation response latency.

### QA-04: Failure handling

Stop the QA relay with Ctrl+C.

Verify that /cmd_vel has zero publishers.

Keep the simulation running with the obstacle in front.

Publish /avoidance/start and observe /avoidance/result.

Observed:
- Robot remained stationary
- Latest result was failed
- /obstacle/detected remained true

This simulates a disconnected motion-command path, not a verified physical motor failure.

Restart the QA relay before running normal avoidance again.

## 12. Known limitations

- Intermittent sensor-stale behavior was observed but not consistently reproduced; root cause remains unconfirmed.
- No simulated IMU publisher was connected. Lane 3 used its fallback turning estimate.
- The wheel-speed mapping is not calibrated for the physical robot.
- The QA relay is not a production state machine.
- Lane 1 state-machine integration has not been tested.
- Gesture, camera/YOLO, audio, password and Telegram have not been tested together in this simulation.
- The saved scene still needs a clean reopen/retest.
- Physical robot QA is pending.

## 13. Safety and shutdown

Stop CoppeliaSim simulation if motion is unexpected.

For normal shutdown, stop the QA processes and bridges deliberately. Removing the Docker container also removes any ROS workspace built only inside it.

Do not treat these simulation results as certification of physical robot safety.

## 14. Integration contract

Follow:
- docs/interfaces.md
- docs/decisions.md
- PLAN.md

In the integrated system, only the Lane 1 state machine should publish /cmd_vel. Lane 3 publishes /avoidance/cmd_vel.
