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
| D3 | Gesture output | Words `forward` `back` `left` `right` `stop` on `/gesture/command`, plus `none` (no hand, or an open hand in the centre zone: zero speed in `DRIVE`, heartbeat only elsewhere). `stop` is a deliberate gesture | `Twist` speeds (tuning spread across lanes); `stop` doubling as "no hand" (freezes avoidance) | 2 |
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
| D11 | What ends blocking after Deny / timeout | Telegram **Resume** button **and** holding the `back` gesture. Both go to `AVOID` (turn away from the person) | Only one of the two; `back` goes to `DRIVE` instead | 1, 4 |
| D12 | Don't ask the same person twice | After a pass, a `person` counts as a plain obstacle for **20 s** (tune on the robot). Known gap: a second person within 20 s isn't checked | Face matching (lookalikes, heavy); no skip at all; skip until the sensor reads clear | 1 |
| D13 | After a person is cleared | Turn away with Lane 3's avoidance | Wait until they leave; hand back to the operator | 1, 3 |
| D14 | Operator decision after 3 wrong passwords | Telegram **Allow** / **Deny** only. No decision gesture for Lane 2 | Thumbs-up gesture; both | 2, 4 |
| D15 | Where the Telegram timeout (40 s since Nov 5, was 30 s) lives | State machine. Alerts carry an id, decisions are JSON `{id, decision}`; `/telegram/blocking` (new id) tells the Telegram node to expire the old buttons | Telegram node; no ids (an old button acts on a new alert) | 4 |
| D28 | What starts `CLASSIFY` | Only an obstacle **appearing** (`/obstacle/detected` false → true). `forward` stays blocked while it's true | Any `true` (re-triggers forever after `failed` / `back`) | 1, 3 |
| D29 | Person walks away during the password | Path clear for 5 s in `CHECKPOINT` → `/password/cancel`, back to `DRIVE` | Wait for the operator | 1, 4 |
| D30 | Stuck states | `CHECKPOINT` with no result in 60 s → `/password/cancel`, `WAIT_OPERATOR`; `AVOID` with no result in 10 s → `/avoidance/cancel`, `failed` | No timeouts | 1 |
| D31 | Camera sees only legs at the checkpoint | Tilt the camera up (`/camera/tilt`) on entering `CHECKPOINT`, keep it up through `WAIT_OPERATOR` and `BLOCKING`, level again on `DRIVE`, `PASS` or `AVOID`. A `camera_tilt` bridge sends the Yahboom `/Servo`. No wait before the photo: the password takes over 10 s, the servo about 0.5 s | Tilt only for the photo; state machine publishes `/Servo` itself (custom message) | 1, 4 |
| D32 | Operator can't hear what the person said | `password_node` keeps the failed answers in memory. Only if the session ends `denied` it saves them as WAVs and publishes each path on `/password/recording`; `telegram_node` sends them as voice replies to the next alert's card, captioned with what the speech engine heard, then deletes the files. Silence has no recording. A `granted` session drops everything | Send each answer as it fails; send audio bytes over ROS; also keep correct answers (they contain the password) | 4 |
| D33 | When the mic opens for the password | After every prompt, `password_countdown` ("three, two, one", ending right after "one") and `password_beep`. `audio_node` publishes `/audio/done` when a clip ends, and `password_node` opens the mic as the beep ends: the beep means "speak now". The first countdown had 0.6 s of silence after "one", which felt like a late start. Measured on the robot (Nov 5): the fixed 2.5 s `listen_delay` opened the mic 0.06 s before the 2.56 s `password_wrong` ended, and 0.44 s of silence after the prompt cut quick answers | Fixed delay after the request; longer fixed delay | 4 |
| D34 | How password_node detects the answer | **Vosk streaming (built):** every mic chunk goes to Vosk from the moment the beep ends, and the first phrase it recognises is the answer, with no loudness threshold. The mic stays open for the node's life. `tools/mic_check.py --digits` on the robot (40% gain, digits-only list): Vosk streaming 10/10 digits, the threshold `listen()` it replaced 6/10. All 4 misses were speech quieter than `energy_threshold` 4000 (loudest 1915 to 3228, room noise 110 to 210). `tools/listen_check.py` runs the same checks through the real `listen_once` | SpeechRecognition `listen()` with an energy threshold (still used by `engine: google`); `webrtcvad` | 1, 4 |

## C. Hardware, models and software

| # | Decision | Picked | Other options considered | Owner to check |
|---|---|---|---|---|
| D16 | Robot OS | Yahboom image, ROS 2 Humble, **headless** (desktop off) | Fresh Ubuntu 22.04 (no official Pi 5 support); Ubuntu 24.04 + Jazzy (doesn't match CI); Pi OS + Humble in Docker (fallback) | 1 |
| D17 | Network | **Phone hotspot** for robot and laptop (also gives Telegram internet) | Campus Wi-Fi (captive portal, multicast and client isolation risks) | 1, 2 |
| D18 | Where inference runs | Gestures on the laptop, YOLO on the robot (moves to the laptop if too slow) | All on the robot; all on the laptop | 2, 5 |
| D19 | Distance sensor | LiDAR if the M1 has one, else front ultrasonic. Lane 3 supports both | ToF; camera depth | 3 |
| D20 | Detection model | YOLO nano (YOLO11n / v8n), COCO pretrained, **NCNN** export, 320 px | PyTorch `.pt` (slower); YOLO small (too slow); MobileNet-SSD (less accurate) | 2, 5 |
| D21 | Detection camera | Robot's onboard camera (also the Telegram photo) | Extra USB webcam at person height | 2 |
| D22 | Microphone | USB mic on the robot. fah (Lane 4) gets it | Yahboom voice module (often fixed words only); laptop mic | 1, 4 |
| D23 | What the person says | **Spoken digits, or one spoken word.** For the robot test (Nov 5) **one digit**: accented English words failed (free speech heard "hello" 0/3). `match_mode: first` checks the first N digits heard (N = password length), so going back to 4 digits needs only a new hash. One digit is guessed 1 time in 10 per try, so it's for testing only | Fixed passphrase; answer to a question | 1, 4 |
| D24 | Speech recognition | **Vosk** offline. The check always listens for the digits (plus `vosk_words`, set on the robot only), so speech maps to the closest digit. `vosk_free_speech: true` adds a second pass with no word list, for the Telegram caption only ("said: …"): free speech as the check misheard accented speech on the robot (Nov 5). Cloud Whisper API is a good fallback but costs money | Google Web Speech (unofficial, can fail); whisper.cpp on the Pi (slow); free speech for the check | 4 |
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

## D. Checked on the robot (5 Nov)

Results from the robot session (#27). Details in [robot-setup.md](robot-setup.md).

| # | Result | Notes |
|---|---|---|
| D16 | **Changed** | Raspberry Pi OS (Debian 12) on the Pi 5, ROS 2 Humble inside Yahboom's Docker container `eager_pascal` (the fallback above). Headless, reached over SSH. Cyclone DDS installed in the container |
| D17 | Confirmed | Robot and laptop on the phone hotspot; discovery works with Cyclone DDS on domain 42. The image defaults to domain 61, now set to 42 in `/root/run_handle.sh` and `/root/.bashrc` |
| D18 | Confirmed | YOLO stays on the robot. Time limit per frame: **1.0 s** (#29). `detector_node` replies in 0.13 to 0.27 s including the wait for a frame, about 0.75 s for the first request, inside the 3 s `CLASSIFY` timeout. Gestures on purin's Mac reach the robot at about 10 Hz |
| D19 | Confirmed | LiDAR fitted: `ydlidar_ros2_driver_node` on `/scan`. Objects below the beam are never seen (Lane 3) |
| D20 | Confirmed | NCNN export of YOLO11n at 320 px runs in the container (`ultralytics`, `ncnn`, NumPy 1.26.4) |
| D21 | Confirmed | `/camera/image_raw`: USB webcam, 640x480, 8 to 10 Hz (about 15 Hz after a second reboot), no depth camera. It sits at floor level, so a person at 0.30 m shows only legs: found in 6 of 6 (shorts) and 4 of 4 (regular trousers), but 2 of 5 for baggy jeans filling the image (Lane 2, open). For the Telegram photo, D31 (#37) tilts the camera up in `CHECKPOINT`, so the photo shows the face |
| D22 | Confirmed | The voice board (sound card 2) has capture and playback and is visible in the container; `audio_player` needs `ALSA_CARD=2`, because the default card is HDMI and silent. At 100% capture (+23 dB) the recording clipped and Vosk missed almost all spoken digits. Now 48 kHz (`mic_sample_rate: 48000`) and 40% capture: Vosk streaming (D34) heard 10/10 digits, 0.00% clipped ([mic-check-results-nov5.md](mic-check-results-nov5.md)). The end-to-end password test on the robot passed (#43) |

## Changes to PLAN.md (made in this PR)

- Password row of the tech stack: online speech recognition → offline Vosk,
  spoken digits (D23, D24). Needs Lane 4's agreement on this PR.
- Distance sensing: "LiDAR or ultrasonic (TBD)" → see D19.
- Internet risk: online speech recognition removed; mitigation is confirming
  the phone hotspot (D17).
