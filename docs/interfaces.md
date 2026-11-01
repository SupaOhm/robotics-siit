# ROS interfaces

The contract between lanes. Lane 1 owns this file. If your PR adds, renames
or changes a topic, update this file in the same PR and tag Lane 1.

Status: **v0.3 (Oct 31), under review.** v0.3 applies Lane 2's review on
PR #4. The reasons for each choice are in [decisions.md](decisions.md)
(D-numbers below). All timing values are starting points to tune on the
robot.

## Rules

- Standard messages only (`std_msgs`, `geometry_msgs`, `sensor_msgs`).
  Structured payloads are JSON in a `std_msgs/String`. No custom message
  package (D1).
- Only the state machine publishes `/cmd_vel`. Anything else that moves the
  robot publishes its own `…/cmd_vel`, and the state machine forwards it (D2).
- Every machine: `ROS_DOMAIN_ID=42`,
  `RMW_IMPLEMENTATION=rmw_cyclonedds_cpp`, on the phone hotspot (D16, D17).
- Request/reply pairs that can arrive late carry an **id**. The state
  machine ignores any reply whose id isn't the one it is waiting for.

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
picks the final name and updates this table. `password_node` is a new
spoken-password node; it replaces the finger-count `src/password_system`
package on `main` (Lane 4).

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
| `/gesture/command` | `std_msgs/String` | gesture_node → state_machine | `forward`, `back`, `left`, `right`, `stop` or `none`. Sent at **10 Hz** (D3, D4) |
| `/cmd_vel` | `geometry_msgs/Twist` | state_machine → base driver | The only command the wheels obey |

- `none` means no hand is seen. In `DRIVE` it sets the speed to zero, so
  the robot never drives on without a hand. In every other state it only
  counts as a heartbeat and doesn't interrupt anything (e.g. `AVOID`).
- `stop` is a deliberate gesture and stops the wheels in every state.
- The state machine turns words into speeds (parameters `linear_speed`,
  `angular_speed`). **No `/gesture/command` for 0.5 s → robot stops.**

### Obstacles and avoidance (Lane 3, D5)

Lane 3's `obstacle_avoidance` topics, with one change to
`/obstacle/detected` (fixed rate, safe start; needs PR #3). The A1 has
Ackermann steering and can't turn in place, so `AVOID` is a three-point
turn: it backs up, then arcs forward.

| Topic | Type | From → To | Meaning |
|---|---|---|---|
| `/obstacle/detected` | `std_msgs/Bool` | avoidance_node → state_machine | Published at a fixed **10 Hz**. `true` while blocked (0.30 m stop, 0.40 m clear), `true` from start-up until the first valid reading, and `true` while the sensor has given no valid reading for `sensor_timeout` |
| `/obstacle/distance` | `std_msgs/Float32` | avoidance_node → anyone | Filtered front distance (m) |
| `/avoidance/start` | `std_msgs/Empty` | state_machine → avoidance_node | Turn away from what is in front |
| `/avoidance/cancel` | `std_msgs/Empty` | state_machine → avoidance_node | Stop turning |
| `/avoidance/cmd_vel` | `geometry_msgs/Twist` | avoidance_node → state_machine | Turn command, only while turning. `linear.x` < 0 while backing up, > 0 while arcing; forward it as is |
| `/avoidance/result` | `std_msgs/String` | avoidance_node → state_machine | One per turn: `done`, `failed` or `cancelled` |
| `/imu/data_raw` | `sensor_msgs/Imu` | base driver → avoidance_node | Gyro z, to measure how far `AVOID` has turned. Published by Yahboom's `Ackman_driver_A1` |

**No `/obstacle/detected` for 1 s → the state machine treats the path as
blocked.** Silence only blocks `forward`. It never counts as an obstacle
appearing, so it doesn't start `CLASSIFY`.

A sensor that fails while the node is running is different: the topic goes
`true`, which may start `CLASSIFY`. That ends as `failed` and returns to
`DRIVE`.

### Detection (Lane 2)

| Topic | Type | From → To | Meaning |
|---|---|---|---|
| `/camera/image_raw` | `sensor_msgs/Image` | camera driver → detector, telegram | Onboard camera (D21). Real topic name confirmed at bring-up |
| `/detect/request` | `std_msgs/String` | state_machine → detector_node | Request id. Classify what is in front now (D7) |
| `/detect/result` | `std_msgs/String` (JSON) | detector_node → state_machine | Exactly one reply per request, with the same `id` (D8) |

```json
{"id": "d7", "kind": "object",  "label": "chair",  "confidence": 0.82, "clip": "found_chair"}
{"id": "d8", "kind": "person",  "label": "person", "confidence": 0.91, "clip": null}
{"id": "d9", "kind": "unknown", "label": null,     "confidence": 0.0,  "clip": "found_obstacle"}
```

- `kind` is `object`, `person` or `unknown`. `clip` is the audio clip id.
- **Person first:** if any `person` in the frame is above the person
  threshold, the result is `person`, whatever else is in frame.
- Otherwise, low confidence or a class not in Lane 2's name table is
  `unknown`.

### Password (Lane 4, D9, D23, D24)

| Topic | Type | From → To | Meaning |
|---|---|---|---|
| `/password/start` | `std_msgs/Empty` | state_machine → password_node | Person found: start a session (3 attempts) |
| `/password/cancel` | `std_msgs/Empty` | state_machine → password_node | Abort: the operator took over, or the person walked away |
| `/password/result` | `std_msgs/String` | password_node → state_machine | One per session: `granted`, `denied` (3 wrong) or `cancelled` |

- The password node plays its own prompts through `/audio/play`
  (`password_prompt`, `password_wrong`, `password_denied`).
- Default engine: Vosk offline, vocabulary limited to the digits (D24).
- What the person says is never published or logged, and the password
  itself is kept out of the repo.

**Simulation input (D27):** CoppeliaSim has no microphone. In sim mode the
password node reads typed attempts from `/password/sim_input`
(`std_msgs/String`) instead of the mic. Use a test password only; this
topic is never used on the robot.

### Audio (Lane 4, D10, D25)

| Topic | Type | From → To | Meaning |
|---|---|---|---|
| `/audio/play` | `std_msgs/String` | anyone → audio_node | Clip id, e.g. `found_chair` |

- Requests that arrive while a clip plays are **queued**, not dropped.
  `alert` interrupts and plays at once.
- The cooldown (same clip not repeated within N s) applies only to
  `found_*` clips.

| Clip id | Says | Played by |
|---|---|---|
| `found_<label>` | "Found a chair", … (Lane 2's name table) | state_machine (`ANNOUNCE`) |
| `found_obstacle` | "Found an obstacle" | state_machine (`ANNOUNCE`, avoidance failed) |
| `password_prompt` | "Say the password" | password_node |
| `password_wrong` | "Wrong, try again" | password_node |
| `password_denied` | "Access denied, calling the operator" | password_node (after 3 wrong) |
| `password_correct` | "Password correct, you may pass" | state_machine (`PASS` after `granted`) |
| `operator_allowed` | "The operator has allowed you to pass" | state_machine (`PASS` after `allow`) |
| `alert` | Alert sound | state_machine (`BLOCKING`) |
| `blocking` | "You may not pass" | state_machine (`BLOCKING`) |

### Telegram (Lane 4, D11, D14, D15, D26)

| Topic | Type | From → To | Meaning |
|---|---|---|---|
| `/telegram/alert` | `std_msgs/String` | state_machine → telegram_node | Alert id. Send a photo from `/camera/image_raw` with **Allow** / **Deny** buttons |
| `/telegram/blocking` | `std_msgs/String` | state_machine → telegram_node | A **new** alert id. Deny or timeout happened: send "Robot is blocking" with a **Resume** button |
| `/telegram/decision` | `std_msgs/String` (JSON) | telegram_node → state_machine | `{"id": "a3", "decision": "allow"}`; `decision` is `allow`, `deny` or `resume` |

- The state machine ignores a decision whose `id` isn't the current alert.
- The 30 s timeout is in the state machine (D15), so the Telegram node
  learns of it from `/telegram/blocking`. On that message it removes the
  old **Allow** / **Deny** buttons and replies "expired" if nobody pressed
  them. On `allow`, `deny` or `resume` it removes the buttons it just used.

### State (Lane 1)

| Topic | Type | From → To | Meaning |
|---|---|---|---|
| `/robot/state` | `std_msgs/String` | state_machine → anyone | Current state, on every change and at 1 Hz (debugging, sim, demo overlay) |

## State machine

```
DRIVE ─obstacle appears─► CLASSIFY ─object / unknown─► ANNOUNCE ─► AVOID ─done─► DRIVE
                             │                                       │
                     person, or no reply                     failed / 10 s ─► DRIVE (operator)
                     after one retry
                             ▼
                        CHECKPOINT ─granted─► PASS ─► AVOID
                          │    │
                          │  path clear 5 s ─► DRIVE (password cancelled)
                   denied / 60 s
                          ▼
                    WAIT_OPERATOR ─allow─► PASS
                          │
                 deny / 30 s timeout
                          ▼
                      BLOCKING ─resume / hold back─► AVOID
```

| State | Wheels follow | Leaves when |
|---|---|---|
| `DRIVE` | Gestures (`none` = zero speed); `forward` ignored while the path is blocked | `/obstacle/detected` **changes** from `false` to `true` |
| `CLASSIFY` | Stopped | `/detect/result` with the current id. No reply in 3 s → retry once with a new id. Still none → `CHECKPOINT` (never `unknown`) |
| `ANNOUNCE` | Stopped | Clip requested, short pause |
| `CHECKPOINT` | Stopped | `/password/result`; path clear for 5 s → `/password/cancel`, `DRIVE`; no result in 60 s → `/password/cancel`, `WAIT_OPERATOR` |
| `PASS` | Stopped | Plays `password_correct` (after `granted`) or `operator_allowed` (after `allow`), short pause; starts the 20 s cleared window |
| `WAIT_OPERATOR` | Stopped | `allow` / `deny` for the current alert id, or 30 s. `resume` is ignored here |
| `BLOCKING` | Stopped, `alert` and `blocking` repeat | `resume` for the current alert id, or `back` held 1 s → `AVOID` |
| `AVOID` | `/avoidance/cmd_vel` | `/avoidance/result`; none in 10 s → `/avoidance/cancel`, then handled as `failed` |

- **Edge trigger:** `DRIVE` only reacts when an obstacle *appears*. After
  avoidance fails or the operator holds `back`, an obstacle that is still
  there doesn't re-trigger `CLASSIFY`. `forward` stays blocked, so the
  operator turns or backs out.
- **Cleared window (D12):** for 20 s after `PASS`, a `person` result is
  handled as `unknown` ("Found an obstacle", turn away, no password).
- **Avoidance failed (D6):** stop, play `found_obstacle`, back to `DRIVE`.
- **Operator override (D11):** in any state except `DRIVE` and `BLOCKING`,
  holding `back` for 1 s cancels what is running (`/password/cancel`,
  `/avoidance/cancel`) and returns to `DRIVE`. `stop` always stops the
  wheels.
- **Ending blocking (D11):** in `BLOCKING`, holding `back` for 1 s does the
  same as **Resume**: go to `AVOID` and turn away from the person.

## Still open

| Question | Owner |
|---|---|
| Real camera topic name and the sensor fitted (bring-up, D19, D21) | Lane 1 |
| Detector confidence threshold for `person` | Lane 2 |
| How far `AVOID` turns, what counts as clear, and the sensor's coverage (front only or wider) | Lane 3 |
| Time limit per YOLO frame on the robot before it moves to the laptop (D18). Must fit the 3 s `CLASSIFY` timeout plus one retry | Lane 5 |
| Removing the finger-count `src/password_system` package once `password_node` lands | Lane 4 |
| Password length and the password itself (kept out of the repo) | Lane 4 |
