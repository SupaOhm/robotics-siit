# ROS interfaces

The contract between lanes. Lane 1 owns this file. If your PR adds, renames
or changes a topic, update this file in the same PR and tag Lane 1.

Status: **draft v0.1 (Oct 31)**. Items marked *proposed* are open until the
owning lane agrees on the PR.

## Rules

- **`std_msgs` / `geometry_msgs` / `sensor_msgs` only.** No custom message
  package, so nobody waits on an interface build, and tests stay ROS-free
  (same approach as `password_system`). Structured payloads are a
  `std_msgs/String` holding JSON.
- Topic names are `/<module>/<thing>`.
- Only the state machine publishes `/cmd_vel`. Every other node that wants to
  move the robot publishes its own `/cmd_vel_<source>`, and the state machine
  picks which one goes through.
- All machines use the same `ROS_DOMAIN_ID` (**42**) on the same Wi-Fi.

## Nodes

| Node | Package | Lane | Runs on |
|---|---|---|---|
| `gesture_node` | `gesture_control` | 2 | Operator laptop |
| `state_machine` | `robot_core` | 1 | Robot |
| Yahboom base driver | vendor | 1 | Robot |
| Camera driver | vendor | 1 | Robot |
| `distance_node` | `obstacle_avoidance` | 3 | Robot |
| `avoid_node` | `obstacle_avoidance` | 3 | Robot |
| `detector_node` | `object_detection` | 2 | Robot (laptop fallback if FPS is too low) |
| `password_node` | `password_system` | 4 | Robot |
| `audio_node` | `audio_player` | 4 | Robot |
| `telegram_node` | `telegram_alert` | 4 | Robot |

Package names are suggestions. The lane picks the final name and updates
this table.

```
 laptop                         robot
 ──────                         ─────
 gesture_node ──/gesture/command──► state_machine ──/cmd_vel──► base driver
                                     ▲  │  ▲
 distance_node ──/obstacle/detected──┘  │  └──/cmd_vel_avoid── avoid_node
                                        │
       /detect/request ─► detector_node ─► /detect/result
       /password/start ─► password_node ─► /password/result
       /audio/play     ─► audio_node
       /telegram/alert ─► telegram_node ─► /telegram/decision
```

## Topics

### Driving

| Topic | Type | Publisher → Subscriber | Meaning |
|---|---|---|---|
| `/gesture/command` | `std_msgs/String` | gesture_node → state_machine | One of `forward`, `back`, `left`, `right`, `stop`. Published at **10 Hz** while the laptop runs, also when idle (`stop`), so it doubles as a heartbeat |
| `/cmd_vel_avoid` | `geometry_msgs/Twist` | avoid_node → state_machine | Turn-away motion, only while avoiding |
| `/cmd_vel` | `geometry_msgs/Twist` | state_machine → base driver | The only command the wheels obey |

The state machine turns gesture words into speeds (parameters
`linear_speed`, `angular_speed`). Lane 2 sends words, not speeds, so speed
tuning happens in one place.

**Link drop:** no `/gesture/command` for **0.5 s** → the state machine
publishes zero velocity and the robot stops. (Answers Lane 2 question 3.)

### Obstacles and avoidance (Lane 3)

| Topic | Type | Publisher → Subscriber | Meaning |
|---|---|---|---|
| `/obstacle/detected` | `std_msgs/Bool` | distance_node → state_machine | `true` when something is closer than the stop distance. Already filtered and debounced (hysteresis is Lane 3's job). Publish at ≥ 10 Hz |
| `/obstacle/range` | `sensor_msgs/Range` | distance_node → anyone | Filtered front distance, for debugging and tuning |
| `/avoid/start` | `std_msgs/Empty` | state_machine → avoid_node | Turn away from the obstacle now |
| `/avoid/done` | `std_msgs/Empty` | avoid_node → state_machine | Turn finished, path ahead is clear |

Whether the sensor is LiDAR (`/scan`) or ultrasonic is hidden behind
`/obstacle/detected`, so the choice doesn't change any other lane.

### Detection (Lane 2)

| Topic | Type | Publisher → Subscriber | Meaning |
|---|---|---|---|
| `/camera/image_raw` | `sensor_msgs/Image` | camera driver → detector, telegram | Robot's onboard camera. Check the real Yahboom topic name at bring-up and update this line |
| `/detect/request` | `std_msgs/Empty` | state_machine → detector_node | Classify what is in front now |
| `/detect/result` | `std_msgs/String` (JSON) | detector_node → state_machine | Exactly one reply per request |

YOLO runs **only on request** (the robot is already stopped), not on every
frame. This is the first FPS mitigation from the risk table.

`/detect/result` JSON:

```json
{"kind": "object", "label": "chair", "confidence": 0.82, "clip": "found_chair"}
{"kind": "person", "label": "person", "confidence": 0.91, "clip": null}
{"kind": "unknown", "label": null, "confidence": 0.0, "clip": "found_obstacle"}
```

- `kind` is `object`, `person` or `unknown`. Low confidence or a class not
  in the name table counts as `unknown`.
- `clip` is the audio clip id from the spoken name table. Lane 2 owns the
  table (class → clip id), and Lane 4 records a clip for each id.
- The detector waits up to ~1 s of frames before it answers, so one bad
  frame doesn't decide.

### Password (Lane 4)

Unchanged from the merged `password_system` contract, so the spoken version
drops in behind the same topics:

| Topic | Type | Publisher → Subscriber | Meaning |
|---|---|---|---|
| `/password/start` | `std_msgs/Empty` | state_machine → password_node | Person found: start a session, reset attempts |
| `/password/cancel` | `std_msgs/Empty` | state_machine → password_node | Abort (person left, operator took over) |
| `/password/result` | `std_msgs/String` | password_node → state_machine | Exactly one per session: `granted`, `denied` (3 fails) or `cancelled` |
| `/password/event` | `std_msgs/String` (JSON) | password_node → audio, UI | Progress (`started`, `wrong`, ...), see `src/password_system/README.md` |

The password node asks for audio itself (prompt, "wrong, try again") through
`/audio/play`. The state machine only plays the outcome clips.

### Audio (Lane 4)

| Topic | Type | Publisher → Subscriber | Meaning |
|---|---|---|---|
| `/audio/play` | `std_msgs/String` | anyone → audio_node | Clip id to play, e.g. `found_chair` |

The audio node owns the cooldown (the same clip doesn't repeat within N s)
and drops requests while a clip is playing, except `alert`, which may
interrupt.

Clip ids the state machine uses (Lane 4 records them):

| Clip id | Says |
|---|---|
| `found_<label>` | "Found a chair", ... (from the name table) |
| `found_obstacle` | "Found an obstacle" |
| `password_correct` | "Password correct, you may pass" |
| `alert` | Alert sound |
| `operator_allowed` | "The operator has allowed you to pass" |

### Telegram (Lane 4)

| Topic | Type | Publisher → Subscriber | Meaning |
|---|---|---|---|
| `/telegram/alert` | `std_msgs/Empty` | state_machine → telegram_node | Take a photo from `/camera/image_raw` and send it with **Allow** / **Deny** buttons |
| `/telegram/decision` | `std_msgs/String` | telegram_node → state_machine | `allow`, `deny` or `resume` |

The **30 s timeout lives in the state machine**, not the Telegram node. After
Deny or timeout, the Telegram node sends a second message with a **Resume**
button, which publishes `resume`.

### State (Lane 1)

| Topic | Type | Publisher → Subscriber | Meaning |
|---|---|---|---|
| `/robot/state` | `std_msgs/String` | state_machine → anyone | Current state name, published on every change and at 1 Hz. For debugging, the sim, and the demo overlay |

## State machine

```
DRIVE ──obstacle──► CLASSIFY ──object/unknown──► ANNOUNCE ──► AVOID ──done──► DRIVE
                       │
                       └──person──► CHECKPOINT ──granted──► PASS ──► AVOID
                                        │
                                     denied
                                        ▼
                                    WAIT_OPERATOR ──allow──► PASS
                                        │
                                 deny / 30 s timeout
                                        ▼
                                     BLOCKING ──resume──► AVOID
```

| State | Wheels follow | Leaves when |
|---|---|---|
| `DRIVE` | Gestures (forward blocked while `/obstacle/detected`) | Obstacle detected |
| `CLASSIFY` | Stopped | `/detect/result` arrives, or 3 s timeout → treat as `unknown` |
| `ANNOUNCE` | Stopped | Clip requested, short pause |
| `CHECKPOINT` | Stopped | `/password/result` |
| `PASS` | Stopped | Clip requested, short pause |
| `WAIT_OPERATOR` | Stopped | `/telegram/decision`, or 30 s |
| `BLOCKING` | Stopped, alert repeats | `resume` |
| `AVOID` | `/cmd_vel_avoid` | `/avoid/done` |

**Operator override:** in any state except `DRIVE`, holding `back` for 1 s
cancels what is running (sends `/password/cancel` if needed) and returns
to `DRIVE` with the robot backing up. `stop` always stops the wheels.
*Proposed.*

## Decisions for Lane 1's open questions

1. **What ends blocking after Deny or timeout?** A Telegram **Resume**
   button (`/telegram/decision` = `resume`), or the operator override.
2. **How do we avoid asking the same person twice?** After `granted` or
   `allow`, the robot ignores `person` results for **20 s**
   (`cleared_cooldown`). During that time a person counts as a plain
   obstacle and the robot turns away without speaking.
3. **What happens after a person is cleared?** The robot turns away using
   the same avoidance as for objects (`PASS` → `AVOID`). It doesn't drive
   through a person.
4. **LiDAR or ultrasonic?** Decided at robot bring-up: LiDAR if the A1 has
   one fitted (covers the sides too), otherwise ultrasonic. No other lane is
   affected (see `/obstacle/detected`).
5. **How does the operator decide?** **Telegram buttons only.** Lane 2 does
   not need a decision gesture. A gesture can be added later if time allows.

## Not decided yet

- Real camera topic name and image size on the robot (bring-up).
- Stop and resume distances (Lane 3).
- Detector confidence threshold for `person` (Lane 2).
- Exact spoken password (Lane 4).
