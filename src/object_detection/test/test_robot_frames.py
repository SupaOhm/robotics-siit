"""Check the rules against frames recorded by the robot's own camera.

robot_frames.json is written by tools/extract_boxes.py: for each recording,
the boxes YOLO found in the frames from the moment the robot stopped, one
every 0.5 s. The robot answers from one frame, so the share of right frames
is its chance of answering right.

  - person recordings: every frame must say person. A missed person skips
    the password, the one failure that isn't on the safe side.
  - everything else: at least 80% of frames must be right.

"known_miss" marks recordings that fail for a known reason; if one starts
passing, remove its known_miss.
"""

import json
import os

import pytest

from object_detection.recorded import answer, needed_share, read_settings

HERE = os.path.dirname(__file__)

# Use the robot's own settings, so tuning them re-checks the recordings.
SETTINGS = read_settings(os.path.join(HERE, "..", "config", "detector.yaml"))

with open(os.path.join(HERE, "robot_frames.json")) as f:
    RECORDINGS = json.load(f)


@pytest.mark.parametrize("recording", [
    pytest.param(r, id=r["bag"], marks=pytest.mark.xfail(
        reason=r["known_miss"], strict=True)) if "known_miss" in r
    else pytest.param(r, id=r["bag"])
    for r in RECORDINGS])
def test_recording(recording):
    said = [answer(frame, SETTINGS) for frame in recording["frames"]]
    right = said.count(recording["expect"]) / len(said)
    assert right >= needed_share(recording["expect"]), "said %s" % said
