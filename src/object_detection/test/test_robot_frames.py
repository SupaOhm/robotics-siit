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
import re

import pytest

from object_detection.classifier import Detection, classify, parse_name_table

HERE = os.path.dirname(__file__)

# Use the robot's own settings, so tuning them re-checks the recordings. CI
# has no YAML library, so read the few lines needed directly.
with open(os.path.join(HERE, "..", "config", "detector.yaml")) as f:
    CONFIG = f.read()
PERSON_THRESHOLD = float(re.search(r"person_threshold:\s*([\d.]+)", CONFIG)[1])
OBJECT_THRESHOLD = float(re.search(r"object_threshold:\s*([\d.]+)", CONFIG)[1])
NAMES = parse_name_table(re.findall(r'^\s*-\s*"([^"]+=[^"]+)"', CONFIG, re.M))

with open(os.path.join(HERE, "robot_frames.json")) as f:
    RECORDINGS = json.load(f)


def answer(boxes):
    # The robot runs YOLO at the lower threshold, so it never sees weaker
    # boxes. The JSON keeps them only so the thresholds can be lowered.
    floor = min(PERSON_THRESHOLD, OBJECT_THRESHOLD)
    detections = [Detection(name, conf, area)
                  for name, conf, area in boxes if conf >= floor]
    result = classify("x", detections, NAMES, PERSON_THRESHOLD,
                      OBJECT_THRESHOLD)
    return result["label"] or result["kind"]


@pytest.mark.parametrize("recording", [
    pytest.param(r, id=r["bag"], marks=pytest.mark.xfail(
        reason=r["known_miss"], strict=True)) if "known_miss" in r
    else pytest.param(r, id=r["bag"])
    for r in RECORDINGS])
def test_recording(recording):
    said = [answer(frame) for frame in recording["frames"]]
    right = said.count(recording["expect"]) / len(said)
    needed = 1.0 if recording["expect"] == "person" else 0.8
    assert right >= needed, "said %s" % said
