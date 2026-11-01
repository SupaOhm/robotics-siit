# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A ROS 2 Humble colcon workspace for a Yahboom RosmasterPi A1 security robot. The operator drives it with hand gestures. It stops at obstacles, names objects aloud, asks people for a spoken password, and alerts the operator on Telegram when a password fails.

Read these before changing behaviour:

- `docs/interfaces.md`: the ROS contract (topics, JSON payloads, state machine). Lane 1 owns it.
- `docs/decisions.md`: the reasons behind it. Code and reviews cite these as D-numbers.
- `CONTEXT.md`: the glossary. Use its terms.
- `PLAN.md`: lanes, owners and the timeline.

## Commands

Building needs ROS 2 Humble (the robot, Ubuntu 22.04, or Docker). macOS can't run it.

```bash
colcon build --symlink-install                # whole workspace
colcon build --packages-select <pkg>          # one package
source install/setup.bash
ros2 launch <pkg> <name>.launch.py
```

Tests run on any laptop, without ROS:

```bash
cd src/<pkg>
python -m pytest test                         # one package
python -m pytest test/test_x.py::test_name    # one test
```

No linter is configured.

CI runs `pytest` in every `src/*/test` folder on Ubuntu 22.04 with Python 3.10. It installs only `pytest` and `python-telegram-bot`, with no ROS, MediaPipe or YOLO, so anything a test imports must work without them. If a package's tests need another library, add it to `.github/workflows/ci.yml`.

## Architecture

The state machine (`robot_core`, Lane 1) is the hub. Each other node is a module that the state machine starts over a topic and hears back from. Nodes don't call each other.

```
gesture_node (laptop) ─/gesture/command─► state_machine ─/cmd_vel─► base driver
avoidance_node ─/obstacle/detected──────►      │
                 /avoidance/start  ─► avoidance_node ─► /avoidance/result
                 /detect/request   ─► detector_node  ─► /detect/result
                 /password/start   ─► password_node  ─► /password/result
                 /audio/play       ─► audio_node
                 /telegram/alert   ─► telegram_node  ─► /telegram/decision
```

Gesture recognition runs on the operator's laptop and everything else on the robot, linked over a phone hotspot. Every machine sets `ROS_DOMAIN_ID=42` and `RMW_IMPLEMENTATION=rmw_cyclonedds_cpp`.

Rules that span packages:

- Only the state machine publishes `/cmd_vel`. Anything else that moves the robot publishes its own `…/cmd_vel`, and the state machine forwards it.
- Standard messages only (`std_msgs`, `geometry_msgs`, `sensor_msgs`). Structured data is JSON in a `std_msgs/String`. There is no custom message package.
- Replies that can arrive late carry an id, and the state machine ignores any other id.
- Failures must land on the safe side. No gesture message for 0.5 s stops the robot. No `/obstacle/detected` for 1 s blocks `forward`. No detector reply after one retry goes to `CHECKPOINT`, because a person must never skip the password.

## Package conventions

- One `ament_python` package per module in `src/<package>/`. Copy the layout of `src/password_system`.
- Put logic in plain Python modules and keep the ROS node thin, so tests run without ROS.
- Import heavy libraries (MediaPipe, Ultralytics) inside the class that needs them, not at module level.
- Subscribe to camera topics with a best-effort QoS such as `qos_profile_sensor_data`.
- Keep NumPy below 2 anywhere `cv_bridge` runs. Humble's `cv_bridge` fails to import with NumPy 2, and `pip install ultralytics` pulls it in unless it's pinned.
- Benchmarks and one-off scripts go in `tools/`, and CoppeliaSim scenes in `sim/`.

## Workflow

- `main` is protected: open a PR from a `lane<N>/<short-topic>` branch, with one approval and passing CI.
- Each lane owns its packages. Only edit another lane's package after agreeing it with that lane, and tag them on the PR.
- If a PR adds or changes a topic, update `docs/interfaces.md` in the same PR and tag Lane 1.
- Keep secrets in environment variables or a gitignored `.env`: the Telegram token and chat id, and the password (`ROBOT_PASSWORD_*`).
- Don't commit model weights. Add a download or export step to the package README instead. Short audio clips are fine.

## Current state

`src/password_system` (finger-count password) is superseded by the spoken `password_node`, and it uses `mp.solutions`, which current MediaPipe no longer has. Other packages live on lane branches until their PRs merge, so check open PRs before assuming a node doesn't exist. The node table in `docs/interfaces.md` treats package names as suggestions, so a package's real name can differ from it.
