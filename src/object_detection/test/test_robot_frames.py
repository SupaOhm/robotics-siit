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


# From the robot's log, 11 Nov (d8 to d10): a bottle at the stop and a person
# standing behind it, as class, confidence and bottom edge. The log has no
# left and right edges, and the rules don't use them.
BOTTLE_PERSON_BEHIND = [
    [("person", 0.89, 0.67), ("bottle", 0.68, 0.85), ("bottle", 0.54, 0.67)],
    [("person", 0.86, 0.67), ("bottle", 0.72, 0.84), ("bottle", 0.62, 0.61)],
    [("person", 0.90, 0.67), ("bottle", 0.85, 0.87)],
]


@pytest.mark.parametrize("frame", BOTTLE_PERSON_BEHIND)
def test_person_behind_the_bottle_does_not_count(frame):
    boxes = [[name, conf, 0.4, 0.0, 0.6, bottom] for name, conf, bottom in frame]
    assert answer(boxes, SETTINGS) == "bottle"


# On the robot at tilt 30 (10 Nov), a bottle at the stop distance ended 0.74
# of the way down the frame. A person standing there ends at the same floor
# line, so person_min_bottom must not rise above it.
STOP_DISTANCE_FLOOR = 0.74


def test_person_at_the_stop_distance_counts():
    person = ["person", 0.5, 0.3, 0.0, 0.7, STOP_DISTANCE_FLOOR]
    bottle_beside = ["bottle", 0.9, 0.8, 0.5, 0.9, 0.8]
    assert answer([person, bottle_beside], SETTINGS) == "person"
