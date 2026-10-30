# Robot setup (Lane 1)

Part 1 compares the options for each part of the robot and picks one. Part 2
is the bring-up checklist that confirms the picks on the real Yahboom
RosmasterPi A1. Other lanes read the results from here.

Status: **proposed (Oct 31)**. The owning lane confirms or changes its row
on the PR. Anything marked *check* depends on what the A1 actually has, so
fill it in during bring-up.

# Part 1: Design decisions

## Summary

| # | Decision | Pick | Owner |
|---|---|---|---|
| D1 | Robot OS and ROS 2 | Yahboom image with ROS 2 Humble, Docker if the board needs it | 1 |
| D2 | Laptop ↔ robot link | Plain ROS 2 DDS on a dedicated router or hotspot | 1 |
| D3 | Where inference runs | Gestures on the laptop, YOLO on the robot (laptop fallback) | 1, 2, 5 |
| D4 | Distance sensor | 2D LiDAR if fitted, else front ultrasonic | 1, 3 |
| D5 | Object detection model | YOLO nano, COCO, NCNN export, 320 px, on request only | 2 |
| D6 | Detection camera | Robot's onboard camera | 2 |
| D7 | Gesture model | MediaPipe Hands, existing code, discrete commands | 2 |
| D8 | Microphone | USB mic, fixed facing the person | 1, 4 |
| D9 | Speech recognition | Vosk offline with a restricted word list | 4 |
| D10 | Voice output | Pre-recorded clips played with `aplay` | 4 |
| D11 | Telegram bot | `python-telegram-bot`, long polling | 4 |
| D12 | Simulation bridge | CoppeliaSim ZeroMQ remote API, with a thin ROS 2 node | 5 |

## D1. Robot OS and ROS 2

| Option | Pros | Cons |
|---|---|---|
| **Yahboom's own image** | Base, camera and LiDAR drivers already work; fastest to a moving robot | Can be a ROS 2 Humble container inside Docker, which means extra steps for devices (mic, camera) and for `pip` |
| Fresh Ubuntu 22.04 + Humble | Same as CI; clean | We port Yahboom's drivers ourselves. Ubuntu 22.04 doesn't officially support the Raspberry Pi 5 |
| Ubuntu 24.04 + Jazzy | Native on Pi 5 | Doesn't match CI (Humble), and Yahboom's drivers may target Humble |

**Pick:** the Yahboom image. Keep ROS 2 Humble so it matches CI. If ROS runs
in Docker, mount the repo, `/dev/snd` and the camera into the container.
**Why:** working drivers on day one matter more than a clean OS. We have 11
days.
*Check:* which Pi the A1 has (`cat /proc/device-tree/model`) and whether
Yahboom's ROS is native or in Docker.

## D2. Laptop ↔ robot link

| Option | Pros | Cons |
|---|---|---|
| **ROS 2 DDS (default)** | No extra code; topics just appear | Multicast discovery fails on many campus and venue Wi-Fi networks |
| DDS + Fast DDS discovery server | Works without multicast | One extra process and environment variable on each machine |
| rosbridge (WebSocket) | Gets through almost any network | Gesture node has to speak rosbridge, not normal ROS 2 |

**Pick:** plain DDS on a network we control, either a travel router or a
phone hotspot that both machines join. Use the discovery server only if
discovery still fails.
**Why:** the demo shouldn't depend on venue Wi-Fi. The robot also needs
internet for Telegram, and a hotspot gives it that.

## D3. Where inference runs

| Option | Pros | Cons |
|---|---|---|
| Everything on the robot | No network dependency for vision | MediaPipe and YOLO compete for the Pi's CPU (the main FPS risk) |
| **Gestures on laptop, YOLO on robot** | Laptop does the continuous work; the robot runs YOLO only while stopped | YOLO speed on the Pi still unknown |
| Everything on the laptop | Fastest models | Robot camera streams over Wi-Fi: lag, bandwidth, and it breaks when the link drops |

**Pick:** gestures on the laptop (already in the plan), YOLO on the robot,
run only on request. If Lane 5's benchmark shows the Pi needs more than ~2 s
per decision, move `detector_node` to the laptop. The topics stay the same.
**Why:** YOLO runs once per stop, not per frame, so even a slow Pi is
acceptable.

## D4. Distance sensor

| Option | Coverage | Strengths | Weaknesses |
|---|---|---|---|
| **2D LiDAR** | 360°, one horizontal plane | Sees sides and rear; tells the avoid logic which way is free; standard `/scan` | Misses obstacles below or above the plane and glass; costs more if not already fitted |
| Ultrasonic (HC-SR04 class) | ~15° cone, front only | Cheap, simple, sees glass | Noisy; misses soft or angled surfaces; no side information, so the turn is blind |
| ToF (VL53L1X class) | Narrow front beam | Precise, small | Front only; sunlight and dark surfaces reduce range |
| Camera depth | Camera's view | No extra part | Needs a depth camera, or a monocular model that is too slow |

**Pick:** LiDAR if the A1 has one fitted. If not, a front ultrasonic, with
the turn direction fixed or alternating.
**Why:** LiDAR also answers Lane 3's "which way do I turn" question. Either
way the sensor sits behind `/obstacle/detected`, so no other lane changes.
*Check:* is a LiDAR fitted, and what are its model and topic?

## D5. Object detection model

| Option | Speed on a Pi | Accuracy | Effort |
|---|---|---|---|
| **YOLO11n / YOLOv8n, NCNN export** | Fastest Ultralytics option on ARM CPU | Good on COCO (person, chair, table, bottle...) | `yolo export format=ncnn`, one line |
| Same model, PyTorch `.pt` | Several times slower | Same | None |
| YOLO small (`s`) | Too slow for the Pi CPU | Higher | None |
| MobileNet-SSD | Fast | Lower; weak on small objects | Different tooling from the team's YOLO code |

Input size: **320 px** to start (about 4× less work than 640). Go up only if
Lane 5 shows misses at stopping distance.

**Pick:** a nano YOLO model, NCNN export, 320 px, pretrained on COCO, no
training. **Why:** we only name 8–10 COCO classes, and pretrained weights
already cover them. Objects outside COCO fall back to "Found an obstacle".
Lane 5 confirms the FPS and the ~2 s per-decision budget.

## D6. Detection camera

| Option | Pros | Cons |
|---|---|---|
| **Robot onboard camera** | Already mounted and aimed; same image goes to the Telegram photo | Fixed height; may be low-res |
| Extra USB webcam | Can mount it at person height | One more part and driver |
| Laptop camera | Already used | Points at the operator, not the obstacle |

**Pick:** the onboard camera. **Why:** it's free and also takes the
Telegram photo. *Check:* can it see a standing person's upper body at the
stopping distance? If not, tilt it up or add a USB webcam.

## D7. Gesture model

| Option | Pros | Cons |
|---|---|---|
| **MediaPipe Hands + rules (existing code)** | Already written; no training; landmarks are robust | Needs fixed rules per gesture |
| MediaPipe Gesture Recognizer | 7 built-in gestures (open palm, fist, thumbs up...) | Fixed set; rewrites existing code |
| Custom classifier | Any gestures | Needs data and training time we don't have |

**Pick:** the existing MediaPipe code, publishing the five words in
`interfaces.md` (`forward`, `back`, `left`, `right`, `stop`). **Why:** it
already works, and discrete words keep the speed tuning in one place
(the state machine). No hand in view means `stop`.

## D8. Microphone

| Option | Pros | Cons |
|---|---|---|
| **USB mic on the robot, pointing forward** | Works with ALSA and any speech library; cheap | Picks up motor noise (the robot is stopped while listening, so this matters little) |
| Yahboom voice module | May already be fitted | Usually recognises only fixed command words, not free speech; *check* |
| Laptop mic | Good quality | Far from the person at the checkpoint |

**Pick:** a USB mic on the robot. Use the Yahboom module only if it can
return free-text speech. *Check:* what the voice module can do and whether
`arecord -l` lists a mic.

## D9. Speech recognition (spoken password)

| Option | Internet | Accuracy in noise | Pi load | Notes |
|---|---|---|---|---|
| Google Web Speech (`SpeechRecognition` lib) | Yes | Good | None | Free and unofficial; can fail or rate-limit without warning |
| OpenAI Whisper / cloud API | Yes | Best | None | Needs an API key and money; ~1–2 s delay |
| **Vosk, small English model + word list** | No | Good for a known phrase | Low | Restricting it to the password's words makes it very robust |
| whisper.cpp tiny/base | No | Good | High on a Pi; several seconds | Slow |

**Pick:** Vosk offline with a restricted word list (for example spoken
digits, or the passphrase's words plus a few decoys). **Why:** it removes
the internet dependency from the risk table, and a restricted word list
handles a noisy room better than open dictation. Online recognition is the
fallback. Lane 4 makes the final call together with "what is said".

## D10. Voice output

| Option | Pros | Cons |
|---|---|---|
| **Pre-recorded clips + `aplay`** | Natural voice; no internet; zero load | Every phrase must be recorded |
| Offline TTS (Piper, espeak-ng) | Any sentence | espeak sounds robotic; Piper is extra load |
| Online TTS | Natural | Needs internet and adds lag |

**Pick:** clips (already in the plan), played with `aplay` from the audio
node. **Why:** the phrase list is short and fixed. Use 16 kHz mono `.wav`
to keep files small.

## D11. Telegram bot

| Option | Pros | Cons |
|---|---|---|
| **`python-telegram-bot`, long polling** | Inline Allow/Deny buttons are easy; no public IP needed | Uses asyncio, so give the ROS node and the bot separate threads |
| `pyTelegramBotAPI` | Simpler, synchronous | Less maintained |
| Webhook | Instant | Needs a public HTTPS address; impossible on lab Wi-Fi |

**Pick:** `python-telegram-bot` with long polling. Token and chat id come
from environment variables (see CONTRIBUTING).

## D12. Simulation bridge

| Option | Pros | Cons |
|---|---|---|
| **ZeroMQ remote API + thin ROS 2 node** | `pip install`, pure Python, works with any ROS version | We write the bridge (publish `/obstacle/detected`, subscribe `/cmd_vel`) |
| simROS2 plugin | Native ROS 2 topics from Lua scripts | Must be compiled for our ROS version; fragile |

**Pick:** ZeroMQ remote API. The bridge only fakes the same topics as the
robot: `/cmd_vel` in; `/obstacle/detected`, `/camera/image_raw` and a fake
`/detect/result` out. **Why:** the state machine can't tell sim from robot,
and that's the point. Microphone and Telegram are tested on the robot only.

# Part 2: Bring-up checklist

## 1. OS and ROS 2

- [ ] Board model (`cat /proc/device-tree/model`): `____`
- [ ] OS image used (D1): `____`
- [ ] If Yahboom runs ROS 2 inside Docker, the container name and how to
      enter it: `____`
- [ ] `ros2 doctor` runs without errors
- [ ] Hostname `____`, IP on the demo network `____`
- [ ] SSH from a laptop works

## 2. Networking with the laptop (D2)

Every machine, in `~/.bashrc`:

```bash
source /opt/ros/humble/setup.bash
export ROS_DOMAIN_ID=42
export ROS_LOCALHOST_ONLY=0
```

- [ ] Robot: `ros2 run demo_nodes_cpp talker`; laptop: `ros2 run demo_nodes_cpp listener` gets the messages
- [ ] Same test the other way round
- [ ] If discovery fails: check that the router allows multicast, and that the
      laptop firewall allows UDP 7400–7600 (or use a Fast DDS discovery server)
- [ ] Gesture laptop OS (needs ROS 2 Humble: Ubuntu 22.04, WSL2, or Docker): `____`

## 3. Hardware

| Device | Check | Result |
|---|---|---|
| Base | `ros2 topic pub --once /cmd_vel geometry_msgs/msg/Twist "{linear: {x: 0.1}}"` moves it, zero stops it | |
| Base driver launch | Command that starts it | `____` |
| Camera (D6) | `ros2 topic list` topic name, `ros2 topic hz` rate, resolution | `____` |
| Distance sensor (D4) | LiDAR fitted? Model, topic (`/scan`?) and rate, or ultrasonic topic | `____` |
| Microphone (D8) | `arecord -l` lists it; `arecord -d 3 t.wav && aplay t.wav` sounds clear | `____` |
| Voice module (D8) | Free speech or fixed command words only? | `____` |
| Speaker (D10) | `aplay` a test `.wav` is loud enough at 2 m | `____` |
| Internet | `ping api.telegram.org` works (Telegram) | |
| Battery | Minutes of driving on a full charge | `____` |

## 4. Repo on the robot

```bash
git clone https://github.com/SupaOhm/robotics-siit.git ~/robotics-siit
cd ~/robotics-siit
colcon build --symlink-install
source install/setup.bash
```

- [ ] Builds on the robot
- [ ] `pip install` works for Lane 2/4 dependencies (ultralytics, mediapipe,
      python-telegram-bot, vosk)

## 5. Hand-off

When this is done, update `docs/interfaces.md` with the real camera topic and
sensor choice, mark each D-row above as confirmed or changed, and tell
Lane 3 (sensor) and Lane 5 (benchmark on the robot).
