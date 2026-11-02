# password_system (Lane 4, spoken password)

`password_node`: when the robot finds a person, it asks for the password.
The person **says the digits** into the robot's USB microphone. The node
recognizes them **offline with Vosk**, using a vocabulary of digit words
only, and checks them. The person gets **3 attempts**. After 3 failures the
node reports `denied`, and the state machine starts the alert and Telegram
flow.

This follows the contract in `docs/interfaces.md` (v0.3: D9, D23, D24, D27).
It's a ROS 2 `ament_python` package. The logic is plain Python, so the tests
run anywhere without ROS or a microphone.

## Interface

| Topic | Type | Direction | Meaning |
|---|---|---|---|
| `/password/start` | `std_msgs/Empty` | in | Person found: start a session (3 attempts) |
| `/password/cancel` | `std_msgs/Empty` | in | Abort: the operator took over, or the person left |
| `/password/result` | `std_msgs/String` | out | One per session: `granted`, `denied` or `cancelled` |
| `/audio/play` | `std_msgs/String` | out | The node's own prompts (see below) |
| `/password/sim_input` | `std_msgs/String` | in | One typed attempt, `input_mode: sim` only (D27). `""` = nobody spoke |

| When | Clip on `/audio/play` |
|---|---|
| Session starts | `password_prompt`: "Say the password" |
| Wrong digits, silence or unclear speech (attempts left) | `password_wrong`: "Wrong, try again" |
| Third failure | `password_denied`: "Access denied, calling the operator" (instead of `password_wrong`) |
| `granted` | None. The state machine plays `password_correct` in `PASS` |

What the person says is never published or logged.

## What counts as an attempt

| What happened | Costs an attempt? |
|---|---|
| Said the right digits | No: `granted` |
| Said other digits | Yes |
| Nobody spoke within `listen_timeout` (6 s) | Yes |
| Spoke, but no digit was recognized | Yes |
| Microphone or speech engine failed (unplugged, busy, engine error) | No. But 3 in a row end the session as `denied`, so the operator decides |

At start-up the node listens to the room for 1 s to set how loud speech
must be (`energy_threshold`), so keep quiet near the robot when it starts.
The threshold then stays fixed: an adaptive one also rose while the
person was talking and cut off a softer last digit.

Before each attempt the node waits `listen_delay` (2.5 s), so it doesn't
record its own prompt clip. The prompt clips must be shorter than that.
Worst case is 3 attempts of about 14 s each, which fits the state machine's
60 s `CHECKPOINT` timeout.

In sim mode, no typed attempt within `sim_timeout` (8.5 s) counts as
silence, so sim timing matches the robot. If `/password/start` arrives
while a session is running, the node publishes `cancelled` for the old
session first, so every session gets exactly one result.

The recognized words are normalized before checking: "four seven one nine",
"4 7 1 9" and "4719" are the same. The homophones "to" / "too" (2), "for"
(4) and "oh" (0) count too.

In the default `exact` mode, the digits heard must be exactly the
password, so saying a long run of digits can't test many codes in one
attempt. Vosk turns any non-digit word into `[unk]`, which is dropped, so
with Vosk "the password is 4719" still counts as "4719". With Google, the
extra words make it wrong. `contains` mode accepts the password anywhere
in a longer run; don't use it at the demo.

## Setting the password (kept out of the repo)

The password and its hash are never committed. With 4 digits, a committed
hash can be cracked in milliseconds. On the robot:

```bash
ros2 run password_system make_password_hash 4 7 1 9   # your digits, not these
```

It prints one line, with the length, salt and hash together:

```bash
export ROBOT_PASSWORD_HASH=4:<salt>:<hash>
```

Add it to the robot's `~/.bashrc`, or to the gitignored `.env`, and load
it before launching. The node refuses to start if it's missing or
malformed. Share
the real password with the team privately, not in the repo or on GitHub.
In simulation, use a different test password.

## Install (robot: Ubuntu 22.04, ROS 2 Humble)

```bash
sudo apt install portaudio19-dev python3-pyaudio flac   # flac: only for engine:=google
pip install SpeechRecognition vosk
```

Download the Vosk model once (about 40 MB) and unzip it on the robot. The
node never downloads it, because the venue may have no internet. Don't
commit the model.

```bash
cd ~ && wget https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip
unzip vosk-model-small-en-us-0.15.zip
```

In mic mode with Vosk, the node refuses to start without
`vosk_model_path`. If the microphone is missing at start-up, the node
logs an error and keeps running: each attempt then reports a service
error, so the session ends as `denied` and the operator decides.

## Build and run

```bash
cd <repo root>
colcon build --packages-select password_system
source install/setup.bash

# Robot, USB microphone, Vosk offline
ros2 launch password_system password.launch.py     vosk_model_path:=$HOME/vosk-model-small-en-us-0.15

# Simulation (D27): typed attempts instead of the mic
ros2 launch password_system password.launch.py input_mode:=sim
ros2 topic pub --once /password/start std_msgs/msg/Empty
ros2 topic pub --once /password/sim_input std_msgs/msg/String "{data: '4 7 1 9'}"
ros2 topic echo /password/result
```

To pick the USB microphone, list the devices, then set `mic_device_index`
in [config/password.yaml](config/password.yaml):

```bash
python3 -c "import speech_recognition as sr; print(list(enumerate(sr.Microphone.list_microphone_names())))"
```

**Fallback engine:** `engine:=google` uses Google Web Speech instead. It
needs the hotspot's internet, and it's unofficial and can fail. Only use it
if Vosk does badly in the venue.

## Try it on a laptop microphone (no ROS)

```bash
pip install SpeechRecognition pyaudio vosk
cd src/password_system
python -m password_system.mic_demo --password 4719     --vosk-model ~/vosk-model-small-en-us-0.15             # a test password
```

Press Enter to start a session. The demo prints what it heard, so you can
check recognition. This is a local tool; the node itself never logs it.

## Tests

```bash
cd src/password_system
python -m pytest test
```

These cover normalization, the verifier (grant, 3-strike lockout, silence,
unclear speech, engine errors, cancel), the stored password format, which
clips and results each step publishes, and Vosk / Google result parsing.

## Tuning

| Parameter | Default | Change it if... |
|---|---|---|
| `listen_delay` | 2.5 s | The robot records its own prompt (raise it) |
| `listen_timeout` | 6 s | People need longer before they start talking |
| `phrase_time_limit` | 5 s | Answers get cut off |
| `match_mode` | `exact` | Keep `exact`. `contains` lets one attempt test many codes |
| `max_service_errors` | 3 | Mic or engine failures before handing over to the operator |
| `mic_device_index` | -1 | The wrong microphone is used |
| `sim_timeout` | 8.5 s | Sim only: time to type an attempt before it counts as silence |
| `energy_threshold` | 0 (measure at start-up) | Digits get cut off or silence is taken as speech. The node logs the value it measured; set a fixed one if the room's noise changes after start-up |

## Files

```
password_system/
  verifier.py       attempts / lockout state machine, result + clip mapping (no ROS)
  normalize.py      recognized words -> digits ("four seven" -> "47")
  speech.py         microphone + Vosk (digits grammar) / Google speech-to-text
  password_node.py  ROS 2 node (contract v0.3)
  hash_tool.py      make_password_hash: prints the ROBOT_PASSWORD_HASH line
  mic_demo.py       laptop demo without ROS
config/password.yaml   tuning only, no password (mode, engine, model path are launch args)
launch/password.launch.py
test/
```
