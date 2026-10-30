# Design decisions (Phase 1)

Decided by Lane 1 (guy, PM) on Oct 31. Each lane checks the rows it owns on
the PR. If you disagree, comment on the row with what you'd pick instead
and why.

Topic details are in [interfaces.md](interfaces.md), and the robot
bring-up checklist is in [robot-setup.md](robot-setup.md).

## A. Interfaces

| # | Decision | Picked | Other options considered | Owner to check |
|---|---|---|---|---|
| D1 | Message types | Standard `std_msgs` / `geometry_msgs` / `sensor_msgs`, JSON in a `String` when structured | Custom `robot_interfaces` package (every lane waits for its build) | All |
| D2 | Who owns `/cmd_vel` | Only the state machine. Others publish their own `/…/cmd_vel` and it forwards one | `twist_mux` (priorities only, no states); every node writes `/cmd_vel` (they fight) | 1, 3 |
| D3 | Gesture output | Words `forward` `back` `left` `right` `stop` on `/gesture/command` | `Twist` speeds (tuning spread across lanes) | 2 |
| D4 | Laptop link drops | Gesture node publishes at 10 Hz; nothing for 0.5 s → robot stops | Keep the last command (drives blind) | 2 |
| D5 | Obstacle topics | Lane 3's `obstacle_avoidance` topics unchanged | Rename to a Lane 1 scheme | 3 |
| D6 | Avoidance reports `failed` | Stop, play a clip, hand driving back to the operator | Send a Telegram alert | 3 |
| D7 | When YOLO runs | Only on request (`/detect/request` → `/detect/result`) | Continuously (Pi CPU load) | 2, 5 |
| D8 | Detection result | JSON `{kind, label, confidence, clip}` | Class name only (name table moves to Lane 1) | 2 |
| D9 | Password interface | `/password/start`, `/password/cancel`, `/password/result`, same pattern as avoidance | ROS 2 action; state machine calls the speech library itself | 4 |
| D10 | Who asks for audio | Any node publishes a clip id on `/audio/play`; audio node owns cooldown | Only the state machine plays audio | 4 |

## B. Behaviour

| # | Question | Picked | Other options considered | Owner to check |
|---|---|---|---|---|
| D11 | What ends blocking after Deny / timeout | Telegram **Resume** button **and** holding the `back` gesture | Only one of the two | 1, 4 |
| D12 | Don't ask the same person twice | After a pass, a `person` counts as a plain obstacle for **20 s** (tune on the robot). Known gap: a second person within 20 s isn't checked | Face matching (lookalikes, heavy); no skip at all; skip until the sensor reads clear | 1 |
| D13 | After a person is cleared | Turn away with Lane 3's avoidance | Wait until they leave; hand back to the operator | 1, 3 |
| D14 | Operator decision after 3 wrong passwords | Telegram **Allow** / **Deny** only. No decision gesture for Lane 2 | Thumbs-up gesture; both | 2, 4 |
| D15 | Where the 30 s Telegram timeout lives | State machine | Telegram node | 4 |

## C. Hardware, models and software

| # | Decision | Picked | Other options considered | Owner to check |
|---|---|---|---|---|
| D16 | Robot OS | Yahboom image, ROS 2 Humble, **headless** (desktop off) | Fresh Ubuntu 22.04 (no official Pi 5 support); Ubuntu 24.04 + Jazzy (doesn't match CI); Pi OS + Humble in Docker (fallback) | 1 |
| D17 | Network | **Phone hotspot** for robot and laptop (also gives Telegram internet) | Campus Wi-Fi (captive portal, multicast and client isolation risks) | 1, 2 |
| D18 | Where inference runs | Gestures on the laptop, YOLO on the robot (moves to the laptop if too slow) | All on the robot; all on the laptop | 2, 5 |
| D19 | Distance sensor | LiDAR if the A1 has one, else front ultrasonic. Lane 3 supports both | ToF; camera depth | 3 |
| D20 | Detection model | YOLO nano (YOLO11n / v8n), COCO pretrained, **NCNN** export, 320 px | PyTorch `.pt` (slower); YOLO small (too slow); MobileNet-SSD (less accurate) | 2, 5 |
| D21 | Detection camera | Robot's onboard camera (also the Telegram photo) | Extra USB webcam at person height | 2 |
| D22 | Microphone | USB mic on the robot | Yahboom voice module (often fixed words only); laptop mic | 1, 4 |
| D23 | What the person says | **Spoken digits** | Fixed passphrase; answer to a question | 4 |
| D24 | Speech recognition | **Vosk** offline, vocabulary limited to the digits. Cloud Whisper API is a good fallback but costs money | Google Web Speech (unofficial, can fail); whisper.cpp on the Pi (slow) | 4 |
| D25 | Voice output | Pre-recorded clips, played with `aplay` | Offline TTS (Piper, espeak) | 4 |
| D26 | Telegram | `python-telegram-bot`, long polling | `pyTelegramBotAPI`; webhook (needs public HTTPS) | 4 |
| D27 | Simulation bridge | CoppeliaSim ZeroMQ remote API + a thin ROS 2 node | simROS2 plugin (compile for our ROS) | 5 |

### Software choices under D16

| Choice | Picked | Instead of |
|---|---|---|
| ROS 2 middleware | **Cyclone DDS** (`RMW_IMPLEMENTATION=rmw_cyclonedds_cpp` on every machine) | Fast DDS (default) |
| Node language | **Python** | C++ |
| YOLO runtime | **NCNN** | PyTorch |
| Images to YOLO | **Raw images over ROS** (one camera node feeds detector and Telegram) | Detector reads the camera itself |
| Remote access | **SSH** | VNC desktop |

## Changes to PLAN.md this implies

- Password row of the tech stack: online speech recognition → offline Vosk,
  spoken digits (D23, D24). Needs Lane 4's agreement on this PR.
- Distance sensing: "LiDAR or ultrasonic (TBD)" → decided at bring-up by
  D19.
