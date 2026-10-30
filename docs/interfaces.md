# ROS interfaces

The contract between lanes. Lane 1 owns this file. If your PR adds, renames
or changes a topic, update this file in the same PR and tag Lane 1.

Status: **v0.2 (Oct 31), under review.** The reasons for each choice are in
[decisions.md](decisions.md) (D-numbers below).

## Rules

- Standard messages only (`std_msgs`, `geometry_msgs`, `sensor_msgs`).
  Structured payloads are JSON in a `std_msgs/String`. No custom message
  package (D1).
- Only the state machine publishes `/cmd_vel`. Anything else that moves the
  robot publishes its own `…/cmd_vel`, and the state machine forwards it (D2).
- Every machine: `ROS_DOMAIN_ID=42`,
  `RMW_IMPLEMENTATION=rmw_cyclonedds_cpp`, on the phone hotspot (D16, D17).

## Nodes

| Node | Package | Lane | Runs on |
|---|---|---|---|
| `gesture_node` | `gesture_control` | 2 | Operator laptop |
| `state_machine` | `robot_core` | 1 | Robot |
| Yahboom base and camera drivers | vendor | 1 | Robot |
| `avoidance_node` | `obstacle_avoidance` | 3 | Robot |
| `detector_node` | `object_detection` | 2 | Robot (laptop if too slow, D18) |
| `password_node` | `password_check` | 4 | Robot |
| `audio_node` | `audio_player` | 4 | Robot |
| `telegram_node` | `telegram_alert` | 4 | Robot |

Package names other than `obstacle_avoidance` are suggestions. The lane
picks the final name and updates this table.

```
 laptop                           robot
 ──────                           ─────
 gesture_node ──/gesture/command──► state_machine ──/cmd_vel──► base driver
                                      ▲   │   ▲
 avoidance_node ─/obstacle/detected───┘   │   └─/avoidance/cmd_vel─ avoidance_node
                                          │
      /avoidance/start   ─► avoidance_node ─► /avoidance/result
      /detect/request    ─► detector_node  ─► /detect/result
      /password/start    ─► password_node  ─► /password/result
      /audio/play        ─► audio_node
      /telegram/alert    ─► telegram_node  ─► /telegram/decision
```

## Topics

### Driving (Lane 2 → Lane 1)

| Topic | Type | From → To | Meaning |
|---|---|---|---|
| `/gesture/command` | `std_msgs/String` | gesture_node → state_machine | `forward`, `back`, `left`, `right` or `stop`. Sent at **10 Hz**, also `stop` when no hand is seen, so it doubles as a heartbeat (D3, D4) |
| `/cmd_vel` | `geometry_msgs/Twist` | state_machine → base driver | The only command the wheels obey |

The state machine turns words into speeds (parameters `linear_speed`,
`angular_speed`). **No `/gesture/command` for 0.5 s → robot stops.**

### Obstacles and avoidance (Lane 3, unchanged from `obstacle_avoidance`, D5)

| Topic | Type | From → To | Meaning |
|---|---|---|---|
| `/obstacle/detected` | `std_msgs/Bool` | avoidance_node → state_machine | `true` while blocked (0.30 m stop, 0.40 m clear), or while the sensor is silent |
| `/obstacle/distance` | `std_msgs/Float32` | avoidance_node → anyone | Filtered front distance (m) |
| `/avoidance/start` | `std_msgs/Empty` | state_machine → avoidance_node | Turn away from what is in front |
| `/avoidance/cancel` | `std_msgs/Empty` | state_machine → avoidance_node | Stop turning |
| `/avoidance/cmd_vel` | `geometry_msgs/Twist` | avoidance_node → state_machine | Turn command, only while turning |
| `/avoidance/result` | `std_msgs/String` | avoidance_node → state_machine | One per turn: `done`, `failed` or `cancelled` |

### Detection (Lane 2)

| Topic | Type | From → To | Meaning |
|---|---|---|---|
| `/camera/image_raw` | `sensor_msgs/Image` | camera driver → detector, telegram | Onboard camera (D21). Real topic name confirmed at bring-up |
| `/detect/request` | `std_msgs/Empty` | state_machine → detector_node | Classify what is in front now (D7) |
| `/detect/result` | `std_msgs/String` (JSON) | detector_node → state_machine | Exactly one reply per request (D8) |

```json
{"kind": "object",  "label": "chair",  "confidence": 0.82, "clip": "found_chair"}
{"kind": "person",  "label": "person", "confidence": 0.91, "clip": null}
{"kind": "unknown", "label": null,     "confidence": 0.0,  "clip": "found_obstacle"}
```

`kind` is `object`, `person` or `unknown`. Low confidence or a class not in
Lane 2's name table is `unknown`. `clip` is the audio clip id.

### Password (Lane 4, D9, D23, D24)

| Topic | Type | From → To | Meaning |
|---|---|---|---|
| `/password/start` | `std_msgs/Empty` | state_machine → password_node | Person found: start a session (3 attempts) |
| `/password/cancel` | `std_msgs/Empty` | state_machine → password_node | Abort (operator took over) |
| `/password/result` | `std_msgs/String` | password_node → state_machine | One per session: `granted`, `denied` (3 wrong) or `cancelled` |

The password node plays its own prompts ("Say the password", "Wrong, try
again") through `/audio/play`. The spoken digits are never published or
logged.

### Audio (Lane 4, D10, D25)

| Topic | Type | From → To | Meaning |
|---|---|---|---|
| `/audio/play` | `std_msgs/String` | anyone → audio_node | Clip id, e.g. `found_chair` |

The audio node owns the cooldown (same clip not repeated within N s) and
drops requests while a clip plays, except `alert`, which interrupts.

Clip ids the state machine uses:

| Clip id | Says |
|---|---|
| `found_<label>` | "Found a chair", … (Lane 2's name table) |
| `found_obstacle` | "Found an obstacle" |
| `password_correct` | "Password correct, you may pass" |
| `alert` | Alert sound |
| `operator_allowed` | "The operator has allowed you to pass" |

### Telegram (Lane 4, D11, D14, D15, D26)

| Topic | Type | From → To | Meaning |
|---|---|---|---|
| `/telegram/alert` | `std_msgs/Empty` | state_machine → telegram_node | Send a photo from `/camera/image_raw` with **Allow** / **Deny** buttons |
| `/telegram/blocking` | `std_msgs/Empty` | state_machine → telegram_node | Deny or timeout happened: send "Robot is blocking" with a **Resume** button |
| `/telegram/decision` | `std_msgs/String` | telegram_node → state_machine | `allow`, `deny` or `resume` |

The 30 s timeout is in the state machine (D15).

### State (Lane 1)

| Topic | Type | From → To | Meaning |
|---|---|---|---|
| `/robot/state` | `std_msgs/String` | state_machine → anyone | Current state, on every change and at 1 Hz (debugging, sim, demo overlay) |

## State machine

```
DRIVE ─obstacle─► CLASSIFY ─object / unknown─► ANNOUNCE ─► AVOID ─done─► DRIVE
                     │                                       │
                     │                                    failed ─► DRIVE (operator)
                     └─person─► CHECKPOINT ─granted─► PASS ─► AVOID
                                    │
                                 denied
                                    ▼
                              WAIT_OPERATOR ─allow─► PASS
                                    │
                           deny / 30 s timeout
                                    ▼
                                BLOCKING ─resume─► AVOID
```

| State | Wheels follow | Leaves when |
|---|---|---|
| `DRIVE` | Gestures; `forward` ignored while `/obstacle/detected` | Obstacle detected |
| `CLASSIFY` | Stopped | `/detect/result`, or 3 s → `unknown` |
| `ANNOUNCE` | Stopped | Clip requested, short pause |
| `CHECKPOINT` | Stopped | `/password/result` |
| `PASS` | Stopped | Clip requested, short pause; starts the 20 s cleared window |
| `WAIT_OPERATOR` | Stopped | `/telegram/decision`, or 30 s |
| `BLOCKING` | Stopped, alert repeats | `resume` |
| `AVOID` | `/avoidance/cmd_vel` | `/avoidance/result` |

- **Cleared window (D12):** for 20 s after `PASS`, a `person` result is
  handled as `unknown` ("Found an obstacle", turn away, no password).
- **Avoidance failed (D6):** stop, play `found_obstacle`, back to `DRIVE`.
- **Operator override (D11):** in any state except `DRIVE`, holding `back`
  for 1 s cancels what is running (`/password/cancel`, `/avoidance/cancel`)
  and returns to `DRIVE`. `stop` always stops the wheels.

## Still open

- Real camera topic name and the sensor fitted (bring-up, D19, D21).
- Detector confidence threshold for `person` (Lane 2).
- Password length and the digits themselves (Lane 4; kept out of the repo).
