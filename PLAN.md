# Project plan: AI gesture-controlled security robot

## Goal

A robot that the operator drives with hand gestures. It stops at obstacles
and names them in Thai, and it acts as a security checkpoint by checking
people with a password.

## System flow

1. The operator drives the robot with hand gestures.
2. The distance sensor detects an obstacle, the robot stops, and the camera
   classifies it.
3. **Object:** the robot says its name in Thai ("เจอเก้าอี้", "เจอโต๊ะ"). If the
   object is unknown or confidence is low, it says "เจอสิ่งกีดขวาง". Then it
   turns away and continues.
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
| Gesture control | OpenCV + MediaPipe (existing code) |
| Object detection | Pretrained YOLO (COCO) + English-to-Thai name table |
| Distance sensing | LiDAR or ultrasonic (TBD) |
| Password | Hand-gesture finger-count sequence (done, `src/password_system`) |
| Audio | Pre-recorded Thai clips |
| Operator alert | Telegram bot |
| Simulation | CoppeliaSim |

## Lanes

| Lane | People | Owns |
|---|---|---|
| 1. Integration, hardware base, PM | guy | ROS nodes/topics/messages, state machine, gesture override, robot OS/ROS setup, porting to robot |
| 2. AI & vision | purin, ohm | Gesture ROS node, YOLO detection, person class, Thai name table |
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
- [ ] Lane 1: install OS / ROS 2 on the robot, confirm hardware works
- [ ] Lane 5: benchmark YOLO + MediaPipe together on the robot, lock the FPS target
- [ ] Lane 6: draft the system architecture document

### Phase 2: Parallel development (Oct 31 – Nov 3)

- [ ] Lane 1: core state machine and gesture command override
- [ ] Lane 2: gesture code as a ROS node; YOLO deployed; Thai name table (8–10 objects)
- [ ] Lane 3: sensor driver, noise filter, avoidance turn logic
- [ ] Lane 4: record audio clips; Telegram bot (password system already done)
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
| YOLO doesn't know walls, doors, boxes | They fall back to "เจอสิ่งกีดขวาง" |
| Telegram needs internet on the robot | Confirm Wi-Fi at the demo venue in Phase 1 |

## Open questions for Lane 1 (decide in Phase 1)

1. Does gesture control use the robot's onboard camera? If so, the operator
   stands in front of the robot and will be detected as a person.
2. After Deny or timeout, what makes the robot stop blocking? (e.g. a Telegram
   "Resume" button)
3. After a correct password, how do we avoid asking the same person again on
   the next distance check?
4. When a person is cleared, does the robot steer around them, wait, or drive on?
5. LiDAR or ultrasonic?
