# Robot session 9 Nov: QA results (Lane 5)

Lane 5's notes from the robot session on Mon 9 Nov (#40, #52). Every result
says which code the robot ran: `b2d5b8c` until 18:02, then `26b95c5` (main
with #51).

## Changed on the robot

None of these are in git.

| What | Change | Undo |
|---|---|---|
| Telegram chat | `TELEGRAM_CHAT_ID` in the clone's `.env` now points to the "Monitor" group (4 members) instead of a private chat. `.env` has no `TELEGRAM_ALLOWED_USERS`, so anyone in the group can press the buttons | Lane 4 has the old private chat id |
| WiFi | The phone hotspot Jz is saved with `autoconnect-priority 10`. At boot the robot joins Jz if it's on, and otherwise starts its own hotspot (HOST, 192.168.1.11) as before | `sudo nmcli connection modify Jz connection.autoconnect-priority 0` |
| Shared clone | Pulled to `26b95c5` at 18:02 from inside `eager_pascal`, then `colcon build --symlink-install`: 7 packages finished | |

## Checked

| Check | Code | Result |
|---|---|---|
| State at start | `b2d5b8c` | `/robot/state` is `DRIVE` |
| `none` for 2 s (`ros2 topic pub -r 10 /gesture/command`) | `b2d5b8c` | Stays still |
| `left` for 2 s | `b2d5b8c` | Turns left, stops by itself when the words stop |
| `forward` with the LiDAR driver not running | `b2d5b8c` | Doesn't move: forward is blocked while the obstacle sensor is silent |
| LiDAR | `b2d5b8c` | `/scan` at 10.05 Hz |
| Every node started by hand | `b2d5b8c` | 10 nodes, `/cmd_vel` has 1 publisher, `DRIVE` |
| `robot_bringup.sh start` and `status` (#50 at `d0b4d6e`) | `26b95c5` | `ok` for `/scan`, `/obstacle/detected`, `/camera/image_raw` and `/robot/state`; 10 nodes; `/cmd_vel publishers: 1` |
| `avoidance_node` after #51 | `26b95c5` | Ready line: `stop=0.40 m, clear=0.50 m from the bumper, sensor 0.15 m behind it`. The stop gap wasn't measured yet |
| Telegram `/start` in the Monitor group | `b2d5b8c` | The bot replies with the group's chat id. With one `telegram_node` running, its log has no `Conflict` |
| ROS from a laptop over the iPhone hotspot | both | Yahboom's Ubuntu 22.04 VM in VMware, network bridged to the laptop's WiFi, domain 42, CycloneDDS (`ros-humble-rmw-cyclonedds-cpp` installed in the VM). It sees `/robot/state`, `/cmd_vel` and `/scan` |
| `gesture_node` keyboard mode from the VM | `b2d5b8c` | Drives the robot. When the key is released, the robot stops |
| `webcam_demo` in the VM (MediaPipe 1.2.2, OpenCV 4.11.0, NumPy 1.21.5) | | Reads `forward`, `back`, `left`, `right`, `none` and `stop` from the laptop webcam |
| CPU with every node running (17:16) | `b2d5b8c` | Load 0.47 / 0.62 / 0.68 on 4 cores, 48.8 °C, `throttled=0x0`, 1.7 of 8 GB RAM. Busiest: base driver 2.5%, `python3` (pi) 2.0%, `avoidance_node` 1.5%, `state_machine` 1.5%, the rest 0.5% or less |

Battery (`/voltage`), light use with little driving:

| Time | Voltage | Note |
|---|---|---|
| 15:25 | | Unplugged, charger LED still red (not full) |
| 15:30 | 12.3 V | |
| 16:07 | 12.1 V | |
| 17:38 | 11.7 V | |

## Detector (#52)

During the session every stop was treated as a person. #52 steps 1 to 5 are
done (output posted there). Step 6, chair try 1, recorded as `chair_qa1`
(138 s):

| Topic | Messages |
|---|---|
| `/camera/image_raw` | 2100 (about 15 per second) |
| `/detect/request` | 6 |
| `/detect/result` | 0 |
| `/cmd_vel` | 1389 |
| `/robot/state` | 147 |

The camera published frames, but `detector_node` didn't reply to any of the
6 requests. Its log (`/tmp/bringup/detector.log` in the container) says why,
for every request of the session (d1 to d8):

```
detector_node ready (5 names, topic /camera/image_raw)
request d1: no camera frame, not replying
...
request d8: no camera frame, not replying
```

So the frames reach the recorder but not `detector_node`. With no reply the
state machine goes to `CHECKPOINT` and asks for the password (D7), which is
"everything is a person". YOLO never ran, so this says nothing yet about how
well it names things. Tries 2 and 3, and the other four objects, aren't done.

## Found

1. **Boot on the hotspot (Lane 1, #50).** The base driver starts before the
   robot has joined the WiFi. Nodes started later can't see `/cmd_vel` or
   `/voltage` (`ros2 topic list` shows only `/parameter_events` and
   `/rosout`). Start the nodes only after the IP shows on the OLED.
2. **WiFi drop (Lane 1).** At 16:58 `wlan0` disconnected and came back as
   172.20.10.3 (it was 172.20.10.4). The nodes kept running, but nothing could
   see them: `ros2 node list` was empty, `/robot/state` was silent, and
   gestures from the laptop did nothing. Once they were started again,
   everything worked. Keep the hotspot phone charging, with the Personal
   Hotspot screen open.
3. **Two `telegram_node`s (Lane 4).** With a second one running, both log
   `Conflict: terminated by other getUpdates request`. Check
   `ps aux | grep [t]elegram_node` in the container before starting one.
4. **Shared clone (Lane 1).** As pi, `git pull` fails with "insufficient
   permission for adding an object to repository database .git/objects":
   some objects are owned by root. Pulling from inside `eager_pascal` works.
   Over the hotspot, `git fetch` once failed with "HTTP/2 stream 1 was not
   closed cleanly"; `git -c http.version=HTTP/1.1 fetch` worked.
5. **`gesture_control` README (Lane 2).** `camera_name:=""` fails in bash
   with `malformed launch argument 'camera_name:='`, because bash drops the
   quotes. On Linux leave it out (`camera_index` is used), or write
   `camera_name:="''"`.
6. **Laptop webcam in a VMware VM (Lanes 2, 5).** It worked at first (16:43),
   then left the VM (`USB disconnect` in `dmesg`). After that VMware couldn't
   connect it ("Driver error"), and the VMware USB Arbitration Service didn't
   respond to stop (error 1053). Once it was connected again, `gesture_node`
   only got `select() timeout`, also with the VM's USB set to 2.0. Gestures
   from a VM aren't reliable enough for the demo: use purin's Mac, with
   keyboard mode as the backup.
7. **Power off (Lane 1).** `sudo poweroff` shuts down the Pi only. The motor
   board, the OLED and the buzzer stay on until the main switch, so a buzzer
   that is beeping keeps beeping.

## Not done yet

The password and Telegram paths were checked by Lane 4 (Paveeranuch,
Tinpatpun) the same day, so they aren't repeated here. Still open for
Lane 5:

- The object path of the #40 full pass, which waits on the detector (above).
- #52 step 6 (5 objects, 3 tries each) and step 7.
- The stop gap after #51, low light, and Lane 4's A7 (a playback failure
  doesn't crash `audio_node`).
