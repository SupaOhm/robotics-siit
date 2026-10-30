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
   - Correct: it confirms out loud and passes.
   - Wrong (3 attempts): it plays an alert and sends a photo to the operator
     on Telegram with **Allow** / **Deny** buttons.
     - Allow: it announces that the person may pass and continues.
     - Deny, or no reply in 30 s: it keeps blocking and the alert continues.

## Tech stack

| Part | Choice |
|---|---|
| Robot | Yahboom RosmasterPi A1, ROS 2 (`ament_python`, colcon) |
| Gesture control | OpenCV + MediaPipe (existing code), runs on the operator's laptop and sends drive commands to the robot over ROS |
| Object detection | Pretrained YOLO (COCO) + spoken name table (class to English phrase) |
| Distance sensing | LiDAR or ultrasonic (TBD) |
| Password | Spoken aloud into the robot's microphone; online speech recognition (what is said is TBD by Lane 4). The merged `src/password_system` finger-count package is superseded |
| Audio | Pre-recorded English clips |
| Operator alert | Telegram bot |
| Simulation | CoppeliaSim |

## Lanes

| Lane | People | Owns |
|---|---|---|
| 1. Integration, hardware base, PM | guy | ROS nodes/topics/messages, state machine, gesture override, robot OS/ROS setup, porting to robot |
| 2. AI & vision | purin, ohm | Gesture ROS node, YOLO detection, person class, spoken name table |
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

- [ ] Lane 1: define ROS nodes, topics and message types in `docs/interfaces.md`
- [ ] Lane 1: install OS / ROS 2 on the robot, confirm hardware works (including the microphone and voice module, for the spoken password)
- [ ] Lane 5: benchmark YOLO + MediaPipe together on the robot, lock the FPS target
- [ ] Lane 6: draft the system architecture document

### Phase 2: Parallel development (Oct 31 – Nov 3)

- [ ] Lane 1: core state machine and gesture command override
- [ ] Lane 2: gesture code as a ROS node; YOLO deployed; spoken name table in English (8–10 objects)
- [ ] Lane 3: sensor driver, noise filter, avoidance turn logic
- [ ] Lane 4: record audio clips; Telegram bot; spoken password (decide what is said, then speech recognition)
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
| MediaPipe + YOLO together drop FPS on the robot | Benchmark by Oct 30; run YOLO only when the robot stops; lower resolution / alternate frames; fallback to laptop inference over Wi-Fi |
| Low light hurts gesture and object recognition | Test in demo lighting early (Lane 5) |
| YOLO doesn't know walls, doors, boxes | They fall back to "Found an obstacle" |
| Telegram and online speech recognition need internet on the robot | Confirm Wi-Fi at the demo venue in Phase 1 |
| A noisy room breaks speech recognition of the spoken password | Test in demo noise early (Lane 5) |

## Open questions for Lane 1 (decide in Phase 1)

Proposed answers: [docs/interfaces.md](docs/interfaces.md#decisions-for-lane-1s-open-questions).

1. After Deny or timeout, what makes the robot stop blocking? (e.g. a Telegram
   "Resume" button)
2. After a correct password, how do we avoid asking the same person again on
   the next distance check?
3. When a person is cleared, does the robot steer around them, wait, or drive on?
4. LiDAR or ultrasonic?
5. After a wrong password, how does the operator decide: Telegram Allow / Deny
   buttons, a hand gesture on the laptop camera (e.g. thumbs-up), or both? This
   also decides whether Lane 2 adds a decision gesture.

## Open questions for Lane 4

1. What exactly does the person say: a fixed passphrase, spoken digits, or an
   answer to a question?
2. What happens to the merged `src/password_system` finger-count package:
   remove it, or keep it as a fallback for a noisy room?

## Open questions for Lane 2

1. Which camera does object detection use: the robot's onboard camera, or
   something else? (Gesture control uses the operator's laptop camera.)
2. Is a decision gesture (e.g. thumbs-up / thumbs-down) needed? Depends on
   Lane 1 question 5.
3. How does the laptop gesture node send drive commands to the robot: ROS 2
   over the same Wi-Fi network, and what happens if the link drops (stop
   the robot)?
4. How does the detector tell a person from the operator or a bystander in
   frame, and what confidence threshold counts as "person"?

## Open questions for Lane 3

1. How far from an obstacle does the robot stop, and how far does it turn
   before resuming?
2. Does the distance sensor cover the sides and rear, or only the front?
3. After a person is cleared, who owns the route around them: Lane 3's
   avoidance logic or Lane 1's state machine?

## Open questions for Lane 5

1. What FPS counts as "good enough" for gesture control and YOLO together?
2. What demo conditions do we test in: lighting, background noise, Wi-Fi?
3. Can the CoppeliaSim scene simulate the microphone (spoken password) and
   the Telegram step, or are those tested only on the robot?

## Open questions for Lane 6

1. Does the report document the original gesture-password design as a
   change, or only the final spoken-password design?
2. Which scenarios does the demo video show (object naming, correct password,
   wrong password, operator decision)?
