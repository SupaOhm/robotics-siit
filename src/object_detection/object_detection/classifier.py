"""Turn YOLO detections into the /detect/result reply.

No ROS or YOLO imports, so the rules can be tested on any laptop.

Rules (docs/interfaces.md, D8):
  - Any person above the person threshold wins, whatever else is in frame,
    if their box reaches at least person_min_bottom of the way down the
    frame. A person close enough to block the robot reaches the bottom edge,
    wherever they stand across the frame; one further back ends higher up.
    person_min_bottom 0 (the default) counts every person.
  - Otherwise name the closest box above the object threshold whose class is
    in the name table: the one whose bottom edge is lowest in the frame. The
    camera looks along the floor, so that is what blocks the robot, not a
    larger chair behind it. Weaker boxes and classes not in the table are
    ignored, so a vague shape, or the floor read as a "dining table", can't
    hide a clear bottle.
  - Anything else is an unknown obstacle.
"""

from dataclasses import dataclass
from typing import Dict, Iterable, Optional, Sequence, Tuple

PERSON = "person"
UNKNOWN_CLIP = "found_obstacle"


@dataclass(frozen=True)
class Detection:
    name: str           # YOLO class name, e.g. "dining table"
    confidence: float
    # x1, y1, x2, y2 as fractions of the frame's width and height, (0, 0) top left
    box: Tuple[float, float, float, float]


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
             object_threshold: float, person_min_bottom: float = 0.0) -> dict:
    """Build the /detect/result reply for one frame's detections."""
    people = [d for d in detections
              if d.name == PERSON and d.confidence >= person_threshold
              and d.box[3] >= person_min_bottom]
    if people:
        best = max(people, key=lambda d: d.confidence)
        return _result(request_id, PERSON, PERSON, best.confidence, None)

    named = [d for d in detections
             if d.name != PERSON and d.name in names
             and d.confidence >= object_threshold]
    if named:
        closest = max(named, key=lambda d: d.box[3])
        label = names[closest.name]
        return _result(request_id, "object", label, closest.confidence,
                       "found_" + label)
    return _result(request_id, "unknown", None, 0.0, UNKNOWN_CLIP)
