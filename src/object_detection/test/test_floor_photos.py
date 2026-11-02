"""Check the rules against real photos taken 15 cm off a classroom floor.

floor_photos.json holds what YOLO11n (NCNN, 320 px) found in each photo, at
confidence 0.10 and above, and the answer the robot should give. The photos
themselves are not in the repo. "known_miss" marks photos YOLO gets wrong; if
one starts passing, remove its known_miss.
"""

import json
import os
import re

import pytest

from object_detection.classifier import Detection, classify, parse_name_table

HERE = os.path.dirname(__file__)

# Use the robot's own settings, so tuning them re-checks the photos. CI has no
# YAML library, so read the few lines needed directly.
with open(os.path.join(HERE, "..", "config", "detector.yaml")) as f:
    CONFIG = f.read()
PERSON_THRESHOLD = float(re.search(r"person_threshold:\s*([\d.]+)", CONFIG)[1])
OBJECT_THRESHOLD = float(re.search(r"object_threshold:\s*([\d.]+)", CONFIG)[1])
NAMES = parse_name_table(re.findall(r'^\s*-\s*"([^"]+=[^"]+)"', CONFIG, re.M))

with open(os.path.join(HERE, "floor_photos.json")) as f:
    PHOTOS = json.load(f)


@pytest.mark.parametrize("photo", [
    pytest.param(p, id=p["photo"], marks=pytest.mark.xfail(
        reason=p["known_miss"], strict=True)) if "known_miss" in p
    else pytest.param(p, id=p["photo"])
    for p in PHOTOS])
def test_photo(photo):
    detections = [Detection(name, conf, area)
                  for name, conf, area in photo["boxes"]]
    result = classify(photo["photo"], detections, NAMES,
                      PERSON_THRESHOLD, OBJECT_THRESHOLD)
    assert (result["label"] or result["kind"]) == photo["expect"]
