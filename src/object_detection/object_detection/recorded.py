"""Apply the rules to boxes YOLO found earlier, without ROS or YOLO.

Used by the photo and recording tests and by tools/extract_boxes.py. On the
robot the node reads its settings as ROS parameters instead.
"""

import re
from typing import Dict, Sequence

from .classifier import Detection, classify, parse_name_table


def read_settings(path: str) -> Dict:
    """The thresholds and name table in config/detector.yaml.

    CI has no YAML library, so read the few lines needed directly.
    """
    with open(path) as f:
        text = f.read()
    return {
        "image_size": int(re.search(r"image_size:\s*(\d+)", text)[1]),
        "person": float(re.search(r"person_threshold:\s*([\d.]+)", text)[1]),
        "object": float(re.search(r"object_threshold:\s*([\d.]+)", text)[1]),
        "names": parse_name_table(
            re.findall(r'^\s*-\s*"([^"]+=[^"]+)"', text, re.M)),
    }


def answer(boxes: Sequence, settings: Dict) -> str:
    """What the robot says for one frame's boxes: a spoken label, "person"
    or "unknown".

    Each box is [class, confidence, x1, y1, x2, y2], with the corners as
    fractions of the frame's width and height.
    """
    # The robot runs YOLO at the lower threshold, so it never sees weaker
    # boxes. The JSON keeps them only so the thresholds can be lowered.
    floor = min(settings["person"], settings["object"])
    detections = [Detection(name, conf, (x2 - x1) * (y2 - y1), (x1, y1, x2, y2))
                  for name, conf, x1, y1, x2, y2 in boxes if conf >= floor]
    result = classify("x", detections, settings["names"],
                      settings["person"], settings["object"])
    return result["label"] or result["kind"]


def needed_share(expect: str) -> float:
    """Share of a recording's frames that must be right for it to pass.

    Every frame for a person: a missed person skips the password, the one
    failure that isn't on the safe side. 80% for anything else.
    """
    return 1.0 if expect == "person" else 0.8
