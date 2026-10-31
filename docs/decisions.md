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
| D3 | Gesture output | Words `forward` `back` `left` `right` `stop` on `/gesture/command`, plus `none` (no hand, heartbeat only). `stop` is a deliberate gesture | `Twist` speeds (tuning spread across lanes); `stop` doubling as "no hand" (freezes avoidance) | 2 |
| D4 | Laptop link drops | Gesture node publishes at 10 Hz; nothing for 0.5 s → robot stops | Keep the last command (drives blind) | 2 |
| D5 | Obstacle topics | Lane 3's `obstacle_avoidance` topics, but `/obstacle/detected` is published at a fixed 10 Hz, starts `true` until the first valid reading, and 1 s of silence counts as blocked | Rename to a Lane 1 scheme; publish only on change (silence looks like a clear path) | 3 |
| D6 | Avoidance reports `failed` | Stop, play a clip, hand driving back to the operator | Send a Telegram alert | 3 |
| D7 | When YOLO runs | Only on request (`/detect/request` carries a request id → `/detect/result`). No reply: retry once, then treat as a person (`CHECKPOINT`) | Continuously (Pi CPU load); timeout → `unknown` (a person could skip the password) | 2, 5 |
| D8 | Detection result | JSON `{id, kind, label, confidence, clip}`. Any `person` above the threshold wins over other objects | Class name only (name table moves to Lane 1); highest confidence wins (a chair can hide a person) | 2 |
| D9 | Password interface | `/password/start`, `/password/cancel`, `/password/result`, same pattern as avoidance. Designed fresh, not on the finger-count `password_system` package, which `password_node` replaces | ROS 2 action; state machine calls the speech library itself; build on `password_system` | 4 |
| D10 | Who asks for audio | Any node publishes a clip id on `/audio/play`. Audio node queues clips (`alert` interrupts) and applies the cooldown to `found_*` only | Only the state machine plays audio; drop clips while one plays | 4 |

## B. Behaviour

| # | Question | Picked | Other options considered | Owner to check |
|---|---|---|---|---|
| D11 | What ends blocking after Deny / timeout | Telegram **Resume** button **and** holding the `back` gesture | Only one of the two | 1, 4 |
| D12 | Don't ask the same person twice | After a pass, a `person` counts as a plain obstacle for **20 s** (tune on the robot). Known gap: a second person within 20 s isn't checked | Face matching (lookalikes, heavy); no skip at all; skip until the sensor reads clear | 1 |
| D13 | After a person is cleared | Turn away with Lane 3's avoidance | Wait until they leave; hand back to the operator | 1, 3 |
| D14 | Operator decision after 3 wrong passwords | Telegram **Allow** / **Deny** only. No decision gesture for Lane 2 | Thumbs-up gesture; both | 2, 4 |
| D15 | Where the 30 s Telegram timeout lives | State machine. Alerts carry an id, decisions are JSON `{id, decision}`; on timeout the Telegram node removes the buttons and replies "expired" | Telegram node; no ids (an old button acts on a new alert) | 4 |
| D28 | What starts `CLASSIFY` | Only an obstacle **appearing** (`/obstacle/detected` false → true). `forward` stays blocked while it's true | Any `true` (re-triggers forever after `failed` / `back`) | 1, 3 |
| D29 | Person walks away during the password | Path clear for 5 s in `CHECKPOINT` → `/password/cancel`, back to `DRIVE` | Wait for the operator | 1, 4 |
| D30 | Stuck states | `CHECKPOINT` with no result in 60 s → `WAIT_OPERATOR`; `AVOID` with no result in 10 s → `failed` | No timeouts | 1 |

## C. Hardware, models and software

| # | Decision | Picked | Other options considered | Owner to check |
|---|---|---|---|---|
| D16 | Robot OS | Yahboom image, ROS 2 Humble, **headless** (desktop off) | Fresh Ubuntu 22.04 (no official Pi 5 support); Ubuntu 24.04 + Jazzy (doesn't match CI); Pi OS + Humble in Docker (fallback) | 1 |
| D17 | Network | **Phone hotspot** for robot and laptop (also gives Telegram internet) | Campus Wi-Fi (captive portal, multicast and client isolation risks) | 1, 2 |
| D18 | Where inference runs | Gestures on the laptop, YOLO on the robot (moves to the laptop if too slow) | All on the robot; all on the laptop | 2, 5 |
| D19 | Distance sensor | LiDAR if the A1 has one, else front ultrasonic. Lane 3 supports both | ToF; camera depth | 3 |
| D20 | Detection model | YOLO nano (YOLO11n / v8n), COCO pretrained, **NCNN** export, 320 px | PyTorch `.pt` (slower); YOLO small (too slow); MobileNet-SSD (less accurate) | 2, 5 |
| D21 | Detection camera | Robot's onboard camera (also the Telegram photo) | Extra USB webcam at person height | 2 |
| D22 | Microphone | USB mic on the robot. fah (Lane 4) gets it | Yahboom voice module (often fixed words only); laptop mic | 1, 4 |
| D23 | What the person says | **Spoken digits** | Fixed passphrase; answer to a question | 4 |
| D24 | Speech recognition | **Vosk** offline, vocabulary limited to the digits. Cloud Whisper API is a good fallback but costs money | Google Web Speech (unofficial, can fail); whisper.cpp on the Pi (slow) | 4 |
| D25 | Voice output | Pre-recorded clips, played with `aplay` | Offline TTS (Piper, espeak) | 4 |
| D26 | Telegram | `python-telegram-bot`, long polling | `pyTelegramBotAPI`; webhook (needs public HTTPS) | 4 |
| D27 | Simulation bridge | CoppeliaSim ZeroMQ remote API + a thin ROS 2 node. In sim, typed attempts on `/password/sim_input` stand in for the mic; Telegram is the real bot over the hotspot | simROS2 plugin (compile for our ROS); fake Telegram too | 5 |

### Software choices under D16

| Choice | Picked | Instead of |
|---|---|---|
| ROS 2 middleware | **Cyclone DDS** (`RMW_IMPLEMENTATION=rmw_cyclonedds_cpp` on every machine) | Fast DDS (default) |
| Node language | **Python** | C++ |
| YOLO runtime | **NCNN** | PyTorch |
| Images to YOLO | **Raw images over ROS** (one camera node feeds detector and Telegram) | Detector reads the camera itself |
| Remote access | **SSH** | VNC desktop |

D28–D30 were added from Lane 2's review on PR #4.

## Changes to PLAN.md (made in this PR)

- Password row of the tech stack: online speech recognition → offline Vosk,
  spoken digits (D23, D24). Needs Lane 4's agreement on this PR.
- Distance sensing: "LiDAR or ultrasonic (TBD)" → see D19.
- Internet risk: online speech recognition removed; mitigation is confirming
  the phone hotspot (D17).
