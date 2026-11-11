"""Check the rules against real photos taken 15 cm off a classroom floor.

floor_photos.json holds what YOLO11n (NCNN, 320 px) found in each photo, at
confidence 0.10 and above, and the answer the robot should give. The photos
themselves are not in the repo. "known_miss" marks photos YOLO gets wrong; if
one starts passing, remove its known_miss.
"""

import json
import os

import pytest

from object_detection.recorded import answer, read_settings

HERE = os.path.dirname(__file__)

# Use the robot's own settings, so tuning them re-checks the photos.
SETTINGS = read_settings(os.path.join(HERE, "..", "config", "detector.yaml"))

with open(os.path.join(HERE, "floor_photos.json")) as f:
    PHOTOS = json.load(f)

# A known_miss shared by several photos, keyed by its short name.
REASONS = {
    # The phone was held level, so the floor rises to meet the horizon and
    # the feet of a person standing in the path end higher in the frame
    # than on the robot's camera, which tilts down. person_min_bottom was
    # measured on the robot; robot_frames.json checks it.
    "level camera": "a person in the path, but on the level phone camera "
                    "their feet end above person_min_bottom (%s)"
                    % SETTINGS["person_min_bottom"],
}


@pytest.mark.parametrize("photo", [
    pytest.param(p, id=p["photo"], marks=pytest.mark.xfail(
        reason=REASONS.get(p["known_miss"], p["known_miss"]), strict=True))
    if "known_miss" in p
    else pytest.param(p, id=p["photo"])
    for p in PHOTOS])
def test_photo(photo):
    assert answer(photo["boxes"], SETTINGS) == photo["expect"]
