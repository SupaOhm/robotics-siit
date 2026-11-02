"""One hand's landmarks -> one drive word. Plain Python, no ROS, MediaPipe or cv2.

Contract (docs/interfaces.md, D3): the words are forward, back, left, right,
stop and none.

- Fist (at most ``fist_max_fingers`` of index..pinky extended) -> ``stop``.
  The thumb is ignored, so a fist with the thumb sticking out is still a fist.
- Open hand near the frame centre (inside ``deadzone_radius``) -> ``none``.
  Resting the hand in the middle never produces ``stop`` (D3).
- Open hand away from the centre -> a direction from the angle of the hand
  centre around the frame centre: 0 = above, +90 = right, +-180 = below
  (same angle as the original notebook).

Landmarks are the 21 MediaPipe hand points as normalized image (x, y),
already mirrored, so "right" on screen is the operator's right.
Distances use ``aspect`` (frame width / height) so x and y share one scale:
lengths are in units of frame height.
"""

import math
from dataclasses import dataclass
from typing import Optional, Sequence, Tuple

WORDS = ("forward", "back", "left", "right", "stop", "none")
DIRECTIONS = ("forward", "back", "left", "right")

WRIST = 0
# (pip, tip) per finger: index, middle, ring, pinky. The thumb is not used.
FINGERS = ((6, 8), (10, 12), (14, 16), (18, 20))
NUM_LANDMARKS = 21

Point = Tuple[float, float]


@dataclass
class Classification:
    word: str
    extended: int          # index..pinky fingers counted as extended
    center: Point          # hand bbox centre, normalized image coords
    angle: float           # degrees, 0 = above centre, +90 = right
    distance: float        # hand centre to frame centre, units of frame height


@dataclass
class ClassifierParams:
    extend_ratio: float = 1.1         # tip-wrist > pip-wrist * ratio -> extended
    fist_max_fingers: int = 1         # extended <= this -> fist -> stop
    deadzone_radius: float = 0.12     # normalized (frame height)
    deadzone_hysteresis: float = 0.02
    forward_half_angle: float = 30.0  # |angle| <= this -> forward
    back_min_angle: float = 150.0     # |angle| >= this -> back
    angle_hysteresis: float = 8.0     # degrees

    def validate(self) -> None:
        if self.extend_ratio <= 0:
            raise ValueError("extend_ratio must be > 0")
        if not 0 <= self.fist_max_fingers < 4:
            raise ValueError("fist_max_fingers must be 0..3")
        if self.deadzone_radius < 0 or self.deadzone_hysteresis < 0:
            raise ValueError("deadzone values must be >= 0")
        if self.deadzone_hysteresis > self.deadzone_radius:
            raise ValueError("deadzone_hysteresis must be <= deadzone_radius")
        if not 0 < self.forward_half_angle < self.back_min_angle < 180:
            raise ValueError("need 0 < forward_half_angle < back_min_angle < 180")
        if self.angle_hysteresis < 0:
            raise ValueError("angle_hysteresis must be >= 0")


def _dist(a: Point, b: Point, aspect: float) -> float:
    return math.hypot((a[0] - b[0]) * aspect, a[1] - b[1])


def count_extended(landmarks: Sequence[Point], ratio: float = 1.1,
                   aspect: float = 1.0) -> int:
    """Index..pinky fingers whose tip is clearly farther from the wrist than
    the PIP joint. Independent of handedness and hand rotation."""
    wrist = landmarks[WRIST]
    n = 0
    for pip, tip in FINGERS:
        if _dist(landmarks[tip], wrist, aspect) > _dist(landmarks[pip], wrist, aspect) * ratio:
            n += 1
    return n


def hand_center(landmarks: Sequence[Point]) -> Point:
    xs = [p[0] for p in landmarks]
    ys = [p[1] for p in landmarks]
    return ((min(xs) + max(xs)) / 2.0, (min(ys) + max(ys)) / 2.0)


def _sector(angle: float, p: ClassifierParams) -> str:
    a = abs(angle)
    if a <= p.forward_half_angle:
        return "forward"
    if a >= p.back_min_angle:
        return "back"
    return "right" if angle > 0 else "left"


def _in_widened(word: str, angle: float, p: ClassifierParams) -> bool:
    """True if ``angle`` is inside ``word``'s sector with every border pushed
    out by ``angle_hysteresis``: the previous word sticks near a border."""
    h = p.angle_hysteresis
    a = abs(angle)
    if word == "forward":
        return a <= p.forward_half_angle + h
    if word == "back":
        return a >= p.back_min_angle - h
    if word == "right":
        return p.forward_half_angle - h < angle < p.back_min_angle + h
    if word == "left":
        return -p.back_min_angle - h < angle < -p.forward_half_angle + h
    return False


def classify(landmarks: Sequence[Point], params: Optional[ClassifierParams] = None,
             prev: Optional[str] = None, frame_center: Point = (0.5, 0.5),
             aspect: float = 1.0) -> Classification:
    """Classify one frame. ``prev`` is the previous raw word, for hysteresis."""
    p = params or ClassifierParams()
    if len(landmarks) != NUM_LANDMARKS:
        raise ValueError("expected %d landmarks, got %d" % (NUM_LANDMARKS, len(landmarks)))

    extended = count_extended(landmarks, p.extend_ratio, aspect)
    center = hand_center(landmarks)
    dx = (center[0] - frame_center[0]) * aspect
    dy = frame_center[1] - center[1]          # image y grows downwards
    angle = math.degrees(math.atan2(dx, dy))
    distance = math.hypot(dx, dy)

    if extended <= p.fist_max_fingers:
        word = "stop"
    else:
        # Deadzone with hysteresis: harder to leave the centre than to stay out.
        if prev in DIRECTIONS:
            radius = p.deadzone_radius - p.deadzone_hysteresis
        else:
            radius = p.deadzone_radius + p.deadzone_hysteresis
        if distance < radius:
            word = "none"
        elif prev in DIRECTIONS and _in_widened(prev, angle, p):
            word = prev
        else:
            word = _sector(angle, p)
    return Classification(word, extended, center, angle, distance)


class GestureClassifier:
    """Stateful wrapper: remembers the previous raw word for hysteresis."""

    def __init__(self, params: Optional[ClassifierParams] = None):
        self.params = params or ClassifierParams()
        self.params.validate()
        self.prev: Optional[str] = None

    def __call__(self, landmarks: Optional[Sequence[Point]], aspect: float = 1.0,
                 frame_center: Point = (0.5, 0.5)) -> Optional[Classification]:
        if landmarks is None:
            self.prev = None
            return None
        result = classify(landmarks, self.params, self.prev, frame_center, aspect)
        self.prev = result.word
        return result
