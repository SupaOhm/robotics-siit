"""Turn YOLO detections into the /detect/result reply.

No ROS or YOLO imports, so the rules can be tested on any laptop.

Rules (docs/interfaces.md, D8):
  - Any person above the person threshold wins, whatever else is in frame.
  - Otherwise look at the largest box, which is usually what blocks the robot.
    It names the object only if it is in the name table and above the object
    threshold. Anything else is an unknown obstacle.
"""

from dataclasses import dataclass
from typing import Dict, Iterable, Optional, Sequence

PERSON = "person"
UNKNOWN_CLIP = "found_obstacle"


@dataclass(frozen=True)
class Detection:
    name: str           # YOLO class name, e.g. "dining table"
    confidence: float
    area: float         # box area in pixels


def parse_name_table(entries: Iterable[str]) -> Dict[str, str]:
    """Parse "yolo class=spoken label" lines into {yolo class: label}."""
    table = {}
    for entry in entries:
        name, sep, label = (part.strip() for part in entry.partition("="))
        if not sep or not name or not label:
            raise ValueError("expected 'yolo class=label', got %r" % entry)
        table[name] = label
    return table


def _result(request_id: str, kind: str, label: Optional[str], confidence: float,
            clip: Optional[str]) -> dict:
    return {"id": request_id, "kind": kind, "label": label,
            "confidence": round(confidence, 2), "clip": clip}


def classify(request_id: str, detections: Sequence[Detection],
             names: Dict[str, str], person_threshold: float,
             object_threshold: float) -> dict:
    """Build the /detect/result reply for one frame's detections."""
    people = [d for d in detections
              if d.name == PERSON and d.confidence >= person_threshold]
    if people:
        best = max(people, key=lambda d: d.confidence)
        return _result(request_id, PERSON, PERSON, best.confidence, None)

    others = [d for d in detections if d.name != PERSON]
    if others:
        largest = max(others, key=lambda d: d.area)
        label = names.get(largest.name)
        if label is not None and largest.confidence >= object_threshold:
            return _result(request_id, "object", label, largest.confidence,
                           "found_" + label)
    return _result(request_id, "unknown", None, 0.0, UNKNOWN_CLIP)
