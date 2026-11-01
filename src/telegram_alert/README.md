# telegram_alert (Lane 4, operator alerts)

`telegram_node`: when a person fails the spoken password 3 times, the state
machine asks this node to send the operator a **photo of the person** on
Telegram with **Allow** / **Deny** buttons. The operator's answer goes back
to the state machine. If nobody answers in 30 s, the robot keeps blocking,
and the node offers a **Resume** button to end the block.

This follows the contract in `docs/interfaces.md` (v0.3: D11, D14, D15,
D26). It uses `python-telegram-bot` with long polling, so no public server
is needed.

## Interface

| Topic | Type | Direction | Meaning |
|---|---|---|---|
| `/telegram/alert` | `std_msgs/String` | in | Alert id, e.g. `a3`. Send the latest camera frame with **Allow** / **Deny** |
| `/telegram/blocking` | `std_msgs/String` | in | A **new** alert id. Deny or 30 s timeout happened: send "Robot is blocking" with **Resume** |
| `/telegram/decision` | `std_msgs/String` (JSON) | out | `{"id": "a3", "decision": "allow"}`. `decision` is `allow`, `deny` or `resume` |
| `/robot/state` | `std_msgs/String` | in | Leaving `WAIT_OPERATOR` or `BLOCKING` (e.g. the operator held `back`) closes that state's buttons |
| `/camera/image_raw` | `sensor_msgs/Image` | in | Camera frames. Only the latest is kept, as raw bytes; it is decoded only when an alert comes in |

**The 30 s timeout is in the state machine (D15), not here.** When it runs
out, the state machine sends `/telegram/blocking`. This node then removes
the old Allow / Deny buttons and marks that message "⌛ No answer in 30 s:
treated as Deny".

What the operator sees:

```
🚨 Checkpoint: this person did not pass the password check.   [photo]
Alert a3 at 14:02:11
Allow this person to pass? No answer in 30 s = Deny.
[ ✅ Allow ] [ ⛔ Deny ]
```

The text doesn't say "3 wrong passwords", because the robot also asks the
operator when the password check gets no result in 60 s (D30). The "30 s"
comes from `operator_timeout`; keep it equal to the state machine's.

After a press, the buttons disappear, the message shows "✅ Allowed by
@name" (or Denied / Resumed), and the decision is published at once.

Rules:
- **Each message takes one press.** Later presses, presses on expired
  messages, and presses on old messages get "This alert is no longer
  active", and nothing is published.
- **A new alert closes older open messages** ("Closed: a newer alert
  replaced this one"). Every message's buttons also carry a token that is
  unique to this run, so an old button can't act on a new alert even if
  alert ids start again at `a1` after the state machine restarts. The state
  machine also ignores decisions whose `id` isn't the current alert.
- **The robot moved on without a press** (e.g. the operator held `back`):
  `/robot/state` leaving `WAIT_OPERATOR` or `BLOCKING` removes that
  state's buttons ("Closed: the robot moved on (now DRIVE)").
- **Only buttons in the operator chat count.** With
  `TELEGRAM_ALLOWED_USERS` set, only those users can press them.
- **No camera frame?** The alert is still sent as text with "(no camera
  image)". A frame older than `max_image_age` gets "(camera image N s old)".
  If the photo upload fails or takes more than 8 s, the alert is sent as
  text instead, so it reaches the operator early in the 30 s. If a slow
  photo still arrives, it has the same buttons: the first press on either
  copy counts, and the other answers "This alert is no longer active".
- **No internet at start-up** (hotspot not up yet): the node keeps trying,
  every 2 s up to every 60 s, and queues alerts until it connects. A wrong
  token stops the node with an error.
- **Network trouble** is retried 3 times. A send that times out is not
  sent again the same way, because it may have arrived (a timed-out photo
  falls back to text, as above). Button presses made while the node was
  stopped are dropped when it restarts.

## Set up the bot (once, about 5 minutes)

1. In Telegram, message **@BotFather**, send `/newbot`, and pick a name. It
   replies with a **token** like `123456789:AAH...`.
2. Make the operator chat: a private chat with the bot, or a group with the
   operator(s) and the bot.
3. Send `/start` to the bot in that chat. Once the bot is running (step 5
   or the demo below), it replies with the **chat id**. Group ids start
   with `-100`.
4. Put both in the gitignored `.env` file at the repo root. **Never commit
   them**, and share the token privately:

   ```bash
   TELEGRAM_BOT_TOKEN=123456789:AAH...
   TELEGRAM_CHAT_ID=-1001234567890
   # optional: only these Telegram user ids may press the buttons
   TELEGRAM_ALLOWED_USERS=11111111,22222222
   ```

   You can also `export` them in the robot's `~/.bashrc` instead. Values
   already in the environment win over the file.

5. To get the chat id for the first time, start the demo or the node with
   only the token and any placeholder `TELEGRAM_CHAT_ID=0`, send `/start`,
   then put the real id in `.env`.

## Install (robot: Ubuntu 22.04, ROS 2 Humble)

```bash
pip install python-telegram-bot      # tested with 22.8
```

`cv_bridge` and OpenCV come with ROS. The robot needs internet through the
phone hotspot (D17). Check it with `ping api.telegram.org`.

## Build and run

```bash
cd <repo root>
colcon build --packages-select telegram_alert
source install/setup.bash
ros2 launch telegram_alert telegram.launch.py env_file:=$HOME/robotics-siit/.env

# Without the state machine: fake an alert, then the timeout
ros2 topic pub --once /telegram/alert std_msgs/msg/String "{data: 'a1'}"
ros2 topic echo /telegram/decision
ros2 topic pub --once /telegram/blocking std_msgs/msg/String "{data: 'a2'}"
```

Set `image_topic` in [config/telegram.yaml](config/telegram.yaml) to the
real camera topic once Lane 1 confirms it at bring-up. Only `env_file` is a
launch argument, so the launch file never overrides the YAML. With
`colcon build --symlink-install` (as in `docs/robot-setup.md`), edits to
the YAML apply without rebuilding.

## Try it on a laptop (no ROS)

```bash
pip install python-telegram-bot
cd src/telegram_alert
python -m telegram_alert.bot_demo --env-file ../../.env --image some_photo.jpg
```

The demo plays the state machine's part. It sends an alert, waits 30 s for
Allow / Deny, then on Deny or no answer sends "Robot is blocking" and waits
for Resume. It prints each decision exactly as the node would publish it.

## Tests

```bash
cd src/telegram_alert
python -m pytest test
```

- `test_alert_book.py` and `test_settings.py` are pure Python, and run in
  CI. They cover the alert, press, timeout and resume flow, ids, permissions,
  and settings.
- `test_bot.py` drives `AlertBot` against a fake Telegram bot: the right
  `send_photo` / edit calls, buttons, photo fallback, timeouts, retries,
  and that a close waits for a send in flight. It needs
  `python-telegram-bot` installed, so CI skips it.

## Files

```
telegram_alert/
  alert_book.py     which messages to send / close, what a press means (no ROS, no Telegram)
  bot.py            AlertBot: python-telegram-bot calls, retries, button handler
  settings.py       TELEGRAM_* from the environment or a .env file
  telegram_node.py  ROS 2 node (contract v0.3): ROS thread + asyncio bot
  bot_demo.py       laptop demo without ROS
config/telegram.yaml   topic and image settings, no secrets
launch/telegram.launch.py
test/
```

## Not done yet / known limits

- **Not yet run against the real Telegram servers.** Tests use a fake
  bot. The node has been built and started on ROS 2 Humble (Docker), but
  not on the robot.
- If a send times out but did arrive, that message keeps its buttons. A
  press on it gets "no longer active" and publishes nothing.
- `/robot/state` closing uses the state names in `docs/interfaces.md`
  (`WAIT_OPERATOR`, `BLOCKING`). If Lane 1 renames them, update
  `STATE_FOR_KIND` in `alert_book.py`.
