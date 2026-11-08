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


@pytest.mark.parametrize("photo", [
    pytest.param(p, id=p["photo"], marks=pytest.mark.xfail(
        reason=p["known_miss"], strict=True)) if "known_miss" in p
    else pytest.param(p, id=p["photo"])
    for p in PHOTOS])
def test_photo(photo):
    assert answer(photo["boxes"], SETTINGS) == photo["expect"]
