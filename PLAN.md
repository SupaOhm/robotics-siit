# Project plan: AI gesture-controlled security robot

## Goal

A robot that the operator drives with hand gestures. It stops at obstacles
and names them in English, and it acts as a security checkpoint by checking
people with a password.

## System flow

1. The operator drives the robot with hand gestures.
2. The distance sensor detects an obstacle, the robot stops, and the camera
   classifies it.
3. **Object:** the robot says its name in English ("Found a chair", "Found a
   table"). If the object is unknown or confidence is low, it says "Found an
   obstacle". Then it turns away and continues.
4. **Person:** the robot asks for a password.
   - Correct: it confirms out loud, turns away and continues (D13).
   - Wrong (3 attempts): it plays an alert and sends a photo to the operator
     on Telegram with **Allow** / **Deny** buttons.
     - Allow: it announces that the person may pass, turns away and continues.
     - Deny, or no reply in 30 s: it keeps blocking and the alert continues,
       until the operator presses **Resume** or holds the `back` gesture. Then
       it turns away (D11).

## Tech stack

| Part | Choice |
|---|---|
| Robot | Yahboom RosmasterPi A1, ROS 2 (`ament_python`, colcon) |
| Gesture control | OpenCV + MediaPipe (existing code), runs on the operator's laptop and sends drive commands to the robot over ROS |
| Object detection | Pretrained YOLO nano (COCO, NCNN export) on the robot's onboard pan-tilt camera, plus a spoken name table (class to English phrase) (D18, D20, D21) |
| Distance sensing | See [D19](docs/decisions.md) (LiDAR if fitted, else front ultrasonic) |
| Password | Spoken digits into the robot's USB microphone, recognised offline with Vosk (D22–D24). The merged `src/password_system` finger-count package is replaced by a new `password_node` |
| Audio | Pre-recorded English clips |
| Operator alert | Telegram bot |
| Simulation | CoppeliaSim |

## Lanes

| Lane | People | Owns |
|---|---|---|
| 1. Integration, hardware base, PM | guy | ROS nodes/topics/messages, state machine, gesture override, robot OS/ROS setup, porting to robot |
| 2. AI & vision | purin (gesture control), ohm (object detection) | Gesture ROS node (purin); YOLO detection, person class, spoken name table (ohm) |
| 3. Navigation & avoidance, co-PM | po | Distance sensor driver, noise filter, threshold, turn/resume logic |
| 4. I/O & external comms | pun, fah | Audio clips + playback cooldown, password system, Telegram bot |
| 5. Simulation & QA | bew, big | CoppeliaSim scene + ROS bridge, FPS benchmark, system testing |
| 6. Docs & presentation | aom | Report, demo video, slides |

## Timeline

### Phase 0: Repo setup (Oct 29)

- [x] GitHub repo created
- [x] First package merged (`password_system`, Lane 4)
- [x] Plan, README, contribution rules, PR template, CI
- [ ] All 9 members added as collaborators
- [x] Lane 1 and Lane 6 names filled in above
- [x] `main` branch protected (PR + 1 review)
- [ ] Everyone has cloned the repo and read [CONTRIBUTING.md](CONTRIBUTING.md)

### Phase 1: Architecture & setup (Oct 29 – 30)

- [x] Lane 1: define ROS nodes, topics and message types in `docs/interfaces.md`
- [ ] Lane 1: install OS / ROS 2 on the robot, confirm hardware works (including the microphone and voice module, for the spoken password)
- [ ] Lane 5: benchmark YOLO on the robot, lock the time limit per frame (gestures run on the laptop, D18)
- [ ] Lane 6: draft the system architecture document

### Phase 2: Parallel development (Oct 31 – Nov 3)

- [ ] Lane 1: core state machine and gesture command override
- [ ] Lane 2 (purin): gesture code as a ROS node on the laptop, sending drive commands to the robot
- [ ] Lane 2 (ohm): YOLO deployed; person class; spoken name table in English (8–10 objects)
- [ ] Lane 3: sensor driver, noise filter, avoidance turn logic
- [ ] Lane 4: record audio clips and audio player
- [x] Lane 4: Telegram bot
- [ ] Lane 4: spoken password (`password_node`)
- [ ] Lane 5: empty CoppeliaSim scene

### Phase 3: Simulation & integration (Nov 4 – 6)

- [ ] Lane 5: bridge CoppeliaSim to ROS; test the state machine and avoidance
- [ ] Lanes 1–4: bug fixes and adjustments

### Phase 4: Hardware deployment & QA (Nov 7 – 9)

- [ ] Lane 1: port nodes to the robot
- [ ] Lane 5: physical QA (object naming, password cases, Telegram timeout, low light)
- [ ] Lanes 2–4: tune confidence thresholds, sensor distances, audio cooldowns

### Phase 5: Delivery (Nov 10 – 11)

- [ ] Code freeze
- [ ] Lane 6: demo video, report, slides
- [ ] All: rehearse the presentation

## Risks

| Risk | Mitigation |
|---|---|
| YOLO is too slow on the robot | Benchmark on the robot (Lane 5); run YOLO only when the robot stops (D7); move it to the laptop over the hotspot if needed (D18) |
| The robot is low, so at 0.30 m the camera may only see feet and a person could skip the password | Floor-level photo test (ohm); if people are missed, add a tilted frame in `CLASSIFY` |
| The chassis may be Ackermann, so it can't turn in place (D6, D13) | Lane 1 confirms at bring-up; if so, `AVOID` needs a reverse and arc |
| Low light hurts gesture and object recognition | Test in demo lighting early (Lane 5) |
| YOLO doesn't know walls, doors, boxes | They fall back to "Found an obstacle" |
| Telegram needs internet on the robot | Confirm the phone hotspot works at the demo venue (D17) |
| A noisy room breaks speech recognition of the spoken password | Test in demo noise early (Lane 5) |

## Open questions

Decided questions are in [docs/decisions.md](docs/decisions.md). Questions
about the ROS contract, such as the `person` threshold and how far `AVOID`
turns, are under "Still open" in [docs/interfaces.md](docs/interfaces.md).

| Question | Owner |
|---|---|
| Is the chassis Ackermann? If so, do `AVOID` and the `left` / `right` gestures need to change? | Lane 1 (confirm), Lanes 2, 3 |
| Is 0.30 m far enough for the camera to see a person? | ohm |
| Which laptop runs `gesture_node`? It needs ROS 2 Humble | purin |
| What FPS counts as good enough for gesture control? | Lane 5 |
| What demo conditions do we test in: lighting, background noise, hotspot? | Lane 5 |
| Who can answer Telegram alerts: one private chat, or a group of operators? | Lane 4 |
| Does the report document the original gesture-password design as a change, or only the final spoken-password design? | Lane 6 |
| Which scenarios does the demo video show (object naming, correct password, wrong password, operator decision)? | Lane 6 |
