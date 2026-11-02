# robotics-siit: AI gesture-controlled security robot

A Yahboom RosmasterPi A1 that the operator drives with hand gestures. It
stops at obstacles, names them in English, and checks people at a
spoken-password checkpoint, alerting the operator on Telegram when a
password fails.

- **Plan, lanes and timeline:** [PLAN.md](PLAN.md)
- **How to contribute:** [CONTRIBUTING.md](CONTRIBUTING.md)

## Layout

This is a ROS 2 colcon workspace. Each module is its own `ament_python`
package under `src/`, created and owned by its lane.

```
src/
  password_system/    Lane 4, spoken password (password_node)
  obstacle_avoidance/ Lane 3, distance sensor, obstacle threshold, turn-away logic
  ...                 other packages are added by their lanes
docs/                 interface contract, architecture, report
sim/                  CoppeliaSim scenes
external/             third-party source kept as git submodules (see below)
tools/                benchmarks and test scripts (not ROS packages)
```

## External sources

| Path | Source | Licence | Used for |
|---|---|---|---|
| `external/mini_project_arduino` | [toonzzzrock/mini_project_arduino](https://github.com/toonzzzrock/mini_project_arduino) | MIT | Existing MediaPipe gesture code (`python_camera.ipynb`) that Lane 2 (purin) ports into `gesture_control` |

It is a git submodule pinned to one commit. Clone with
`git clone --recurse-submodules`, or run `git submodule update --init` in an
existing clone. It is not a ROS package: do not edit it here, copy what is
needed into `src/`.

## Build

On a machine with ROS 2 (the robot, or Ubuntu / Docker with ROS 2 Humble):

```bash
git clone https://github.com/SupaOhm/robotics-siit.git
cd robotics-siit
colcon build --symlink-install
source install/setup.bash
```

Keep the logic in plain Python modules and keep the ROS node thin, as
`password_system` does. Then the tests run on any laptop without ROS:

```bash
cd src/<package>
python -m pytest test
```
