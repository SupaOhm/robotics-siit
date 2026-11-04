# Gesture link test (Lane 2, purin)

Steps for the first test of the operator laptop (purin's M1 Mac) against the
robot over the phone hotspot. It closes `PLAN.md` "laptop → robot link" and
the two talker/listener boxes in [robot-setup.md](robot-setup.md) §2.

Mac commands run in the macOS Terminal (zsh) from the repo root. Robot
commands are for guy, on the robot over SSH (inside the container, if ROS
runs in Docker).

## 0. Before you start

Ask guy to confirm on the robot:

```bash
echo $ROS_DOMAIN_ID          # must be 42 (the Yahboom image defaults to 61)
echo $RMW_IMPLEMENTATION     # must be rmw_cyclonedds_cpp
echo $ROS_LOCALHOST_ONLY     # must be 0 or empty
hostname -I                  # the robot's IP on the hotspot
```

On the Mac, with any VPN off first. Tailscale counts (`tailscale down`): its
multicast route hides ROS nodes from each other, even on the same Mac, so
`check` fails with 0 messages.

```bash
git checkout main && git pull
bash tools/mac_ros_setup.sh            # rebuilds if anything changed; safe to re-run
bash tools/mac_ros_setup.sh check      # expect PASS, ~10 Hz
```

Join the Mac to the same phone hotspot as the robot (not campus Wi-Fi, D17).
Turn off any VPN. Then:

```bash
ping -c 3 <ROBOT_IP>                   # must reply before any ROS test makes sense
```

## 1. Open a ROS terminal on the Mac

Each new Mac terminal needs the env. Print the lines once:

```bash
bash tools/mac_ros_setup.sh shell
```

Paste what it prints (the `eval`, `conda activate ros_env` and `source`
lines), then check:

```bash
echo $ROS_DOMAIN_ID $RMW_IMPLEMENTATION   # 42 rmw_cyclonedds_cpp
ros2 daemon stop                          # an old daemon keeps the last network's address
```

If macOS asks whether python may accept incoming network connections,
click Allow. ROS 2 needs it.

## 2. Talker and listener (robot-setup.md §2)

Robot to Mac:

```bash
# robot (guy)
ros2 run demo_nodes_cpp talker
# Mac
ros2 run demo_nodes_cpp listener       # expect "I heard: [Hello World: N]"
```

Mac to robot:

```bash
# Mac
ros2 run demo_nodes_cpp talker
# robot (guy)
ros2 run demo_nodes_cpp listener
```

Both directions must work. If not, go to section 5 before going on.

## 3. `/gesture/command` on the robot

Mac, camera mode:

```bash
bash tools/mac_ros_setup.sh run        # Ctrl-C stops
```

Robot (guy):

```bash
ros2 topic echo /gesture/command       # words change as you move your hand
ros2 topic hz /gesture/command         # about 10 Hz, steady
```

Go through each gesture and read the word off guy's screen:

| Hand | Word on the robot |
|---|---|
| Fist | `stop` (at once) |
| Open hand above the centre | `forward` |
| Open hand below the centre, held | `back` |
| Open hand left / right | `left` / `right` |
| Open hand in the centre, or no hand | `none` |

Then check the safe side (D4):

- Ctrl-C on the Mac: the robot sees `none`, then nothing.
- With the node running, turn the Mac's Wi-Fi off for a few seconds: the
  messages stop on the robot. Turn it back on: they come back without
  restarting anything.

Note the `hz` rate and any gaps for the PR.

If the camera misbehaves, keyboard mode tests the link the same way:

```bash
bash tools/mac_ros_setup.sh keyboard   # w/a/s/d, space = stop, x = none
```

## 4. Only once guy's state machine runs on the robot

Not part of this test. With the robot on blocks (wheels off the ground)
first, `bash tools/mac_ros_setup.sh run` should drive the wheels through
the state machine. Do not run anything that publishes `/cmd_vel` from the
Mac: only the state machine publishes it.

## 5. If nothing arrives

Work down the list; re-run section 2 after each fix.

1. `ping` fails: not on the same hotspot, or the phone isolates clients.
   Try another phone.
2. Domain or RMW differs on either side (section 0, section 1).
3. Stale discovery cache, on both machines:
   ```bash
   ros2 daemon stop
   ```
4. macOS firewall: System Settings > Network > Firewall. Allow python, or
   turn it off for the test.
5. The phone blocks multicast (some iPhones do, robot-setup.md §2).
   Tell Cyclone DDS where the other machine is, in every terminal on that
   machine, then restart the nodes. Not yet tried on our hardware.

   Mac (`en0` is usually the Mac's Wi-Fi; check with `ifconfig en0`):
   ```bash
   export CYCLONEDDS_URI='<CycloneDDS><Domain><General><Interfaces><NetworkInterface name="en0"/></Interfaces><AllowMulticast>false</AllowMulticast></General><Discovery><Peers><Peer address="ROBOT_IP"/></Peers><ParticipantIndex>auto</ParticipantIndex><MaxAutoParticipantIndex>50</MaxAutoParticipantIndex></Discovery></Domain></CycloneDDS>'
   ```
   Robot: the same line with `MAC_IP` in the peer and the robot's
   interface name (often `wlan0`). Get the Mac's IP with
   `ipconfig getifaddr en0`.
6. Still nothing: try another phone, or fall back to Fast DDS with a
   discovery server (robot-setup.md §2). That changes D17's setup, so
   agree it with guy first.

## 6. When it passes

- Tick robot-setup.md §2 lines 33 and 34 (or ask guy to, it's his file).
- Tick `PLAN.md` "Lane 2 (purin): laptop → robot link" in a `lane2/` PR,
  with the `hz` rate and the phone model in the description.
- If section 5 step 5 was needed, write the working `CYCLONEDDS_URI` into
  robot-setup.md so every machine uses it.
