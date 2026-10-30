# password_system (Lane 4, spoken password)

When the robot finds a person, it asks for a **spoken password**. The
microphone records the answer, a speech engine turns it into text, and the
text is checked. The demo password is **"one three five two"**. The person
gets **3 attempts**. After 3 failures the node reports `denied`, and the main
state machine starts the alert and Telegram flow.

ROS 2 (`ament_python`) package. The logic is plain Python, so it can be
tested and tried on a laptop without ROS.

## What counts as an attempt

| What happened | Event | Costs an attempt? |
|---|---|---|
| Said the password | `granted` | Session ends, access granted |
| Said something else | `wrong` | Yes |
| Nobody spoke within `listen_timeout` (6 s) | `no_speech` | Yes |
| Spoke, but nothing could be transcribed | `unclear` | Yes |
| Speech engine failed (no internet, mic error) | `service_error` | No. But 3 in a row ends the session as `denied`, so the operator decides on Telegram |

Speech engines write the same words in different ways, so the text is
**normalized** before comparing: "one three five two", "1 3 5 2", "1,352"
and "หนึ่ง สาม ห้า สอง" all become `1352`. Case, spaces and punctuation are
ignored. Common homophones are mapped too ("to" / "too" become 2, "for"
becomes 4). In the default `contains` mode, extra words are fine: "the
password is one three five two" passes.

## Interface (for the main state machine, audio, and Telegram)

All messages are standard `std_msgs`, so there is no custom message package.

| Topic | Type | Direction | Meaning |
|---|---|---|---|
| `/password/start` | `std_msgs/Empty` | in | Person detected: start a session (resets attempts) |
| `/password/cancel` | `std_msgs/Empty` | in | Abort the session (e.g. person left) |
| `/password/result` | `std_msgs/String` | out | Exactly one per session: `granted`, `denied` (send the alert), or `cancelled` |
| `/password/event` | `std_msgs/String` (JSON) | out | Progress, for audio prompts and UI |
| `/password/text` | `std_msgs/String` | in | One attempt as text, only in `input_mode: topic_only` (sim / testing). `""` = nobody spoke |

Event JSON: `{"type": "wrong", "attempts_left": 2}`

| `type` | Suggested audio clip (P6) |
|---|---|
| `started` | "Please say the password." |
| `listening` | Short beep: the mic is open now |
| `wrong` | "Wrong password, please try again." |
| `no_speech` / `unclear` | "Sorry, I didn't hear that. Please try again." |
| `service_error` | None, or "Please wait." |
| `granted` | "Password verified. You may pass." |
| `locked_out` | Alert sound (the state machine also gets `denied` on `/password/result`) |
| `cancelled` | None |

What was heard is never published, and is logged only when
`log_transcripts: true` (use that just for tuning).

**Microphone vs. speaker:** after `started` and after each failure, the node
waits `listen_delay` (2.5 s) before it opens the mic, so the robot doesn't
record its own prompt. Each clip that plays before listening must be shorter
than that, or raise `listen_delay`.

Expected use by the main state machine:

```
person detected  -> publish /password/start
/password/result == "granted"   -> confirm out loud, mark safe, pass
/password/result == "denied"    -> alert sound + Telegram photo with Allow/Deny
person gone                     -> publish /password/cancel
```

## Install

```bash
# On the robot (Ubuntu + ROS 2 Humble)
sudo apt install portaudio19-dev python3-pyaudio flac
pip install SpeechRecognition
pip install vosk                      # only for engine: vosk (offline)
```

`flac` is needed by the Google engine on Linux.

## Build and run

```bash
cd <repo root>
colcon build --packages-select password_system
source install/setup.bash

# On the robot, with the microphone
ros2 launch password_system password.launch.py               # google, en-US
ros2 launch password_system password.launch.py engine:=vosk  # offline

# Simulation / no microphone: type attempts as text
ros2 launch password_system password.launch.py input_mode:=topic_only
ros2 topic pub --once /password/start std_msgs/msg/Empty
ros2 topic pub --once /password/text std_msgs/msg/String "{data: 'one three five two'}"
ros2 topic echo /password/result
```

To pick the microphone, list the devices and set `mic_device_index` in
[config/password.yaml](config/password.yaml):

```bash
python3 -c "import speech_recognition as sr; print(list(enumerate(sr.Microphone.list_microphone_names())))"
```

### Choosing the engine

| | `google` (default) | `vosk` |
|---|---|---|
| Internet | Needed (the robot needs it for Telegram anyway) | Not needed |
| Accuracy | Best | Good for short English words and digits |
| Speed on the Pi | About 1 s round trip | Runs locally, small model is fine on a Pi |
| Thai | `language: th-TH` | No official Thai model |

If the venue Wi-Fi is unreliable, switch to `vosk`. The first run downloads
the small English model (about 40 MB). Or download it once and set
`vosk_model_path`.

### Change the password

```bash
ros2 run password_system make_password_hash four two seven one
```

Paste the printed `password_chars`, `salt` and `password_hash` into
[config/password.yaml](config/password.yaml). Only a salted SHA-256 of the
normalized text is stored, so the password isn't readable in the repo.

Pick digits or short, distinct words, which speech engines get right. A
spoken password can be overheard, and 4 digits is a small keyspace, so this
is a checkpoint demo, not real security. The 3-attempt limit is what
protects it.

### Try it on a laptop microphone (no ROS)

```bash
pip install SpeechRecognition pyaudio
cd src/password_system
python -m password_system.mic_demo                      # password "one three five two"
python -m password_system.mic_demo --engine vosk
python -m password_system.mic_demo --language th-TH --password "เปิด ประตู"
```

Press Enter to start a session. The demo prints what it heard, so you can
check recognition before tuning.

## Tests

```bash
cd src/password_system
python -m pytest test
```

These cover normalization (digit words, Thai, punctuation), the verifier
(grant, `contains` vs `exact`, 3-strike lockout, silence and unclear speech,
service errors, cancel), and parsing of Google / Vosk results. No microphone
is needed.

## Tuning

| Parameter | Default | Change it if... |
|---|---|---|
| `listen_delay` | 2.5 s | The robot records its own prompt (raise it) |
| `listen_timeout` | 6 s | People need longer before they start talking |
| `phrase_time_limit` | 5 s | Answers get cut off |
| `match_mode` | `contains` | Use `exact` to reject extra words |
| `max_service_errors` | 3 | Engine failures before handing over to the operator |
| `mic_device_index` | -1 | The wrong microphone is used |

## Files

```
password_system/
  verifier.py       attempts / lockout state machine (no ROS)
  normalize.py      transcription -> comparable text (digit words, Thai, punctuation)
  speech.py         microphone + google / vosk speech-to-text
  password_node.py  ROS 2 node wiring the above to topics
  hash_tool.py      make_password_hash CLI
  mic_demo.py       laptop demo without ROS
config/password.yaml
launch/password.launch.py
test/
```
