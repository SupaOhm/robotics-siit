"""Count raised fingers from MediaPipe Hands landmarks.

Uses distances from the wrist / palm instead of "tip above joint" checks,
so it works whatever way the hand is rotated and needs no handedness.
MediaPipe is only imported by ``HandFingerCounter`` so the pure function
can be tested without it.
"""

import math
from typing import Optional, Sequence, Tuple

Point = Tuple[float, float]

WRIST = 0
THUMB_MCP, THUMB_TIP = 2, 4
PINKY_MCP = 17
# (tip, pip) for index, middle, ring, pinky
FINGERS = ((8, 6), (12, 10), (16, 14), (20, 18))

# Tuning: a finger counts as raised when its tip is this much farther from
# the wrist than its middle joint. Raise the values if curled fingers count.
FINGER_RATIO = 1.15
THUMB_RATIO = 1.2


def _dist(a: Point, b: Point) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def count_fingers(points: Sequence[Point]) -> int:
    """Number of raised fingers (0-5) from 21 (x, y) landmarks in pixels."""
    if len(points) != 21:
        raise ValueError("expected 21 hand landmarks, got %d" % len(points))
    wrist = points[WRIST]
    count = 0
    for tip, pip in FINGERS:
        if _dist(points[tip], wrist) > _dist(points[pip], wrist) * FINGER_RATIO:
            count += 1
    # Thumb: extended when the tip is well away from the pinky base,
    # compared with the thumb's own base joint.
    pinky_base = points[PINKY_MCP]
    if _dist(points[THUMB_TIP], pinky_base) > _dist(points[THUMB_MCP], pinky_base) * THUMB_RATIO:
        count += 1
    return count


class HandFingerCounter:
    """Wraps MediaPipe Hands; returns a finger count per BGR frame."""

    def __init__(self, min_detection_confidence: float = 0.6,
                 min_tracking_confidence: float = 0.5):
        import mediapipe as mp  # lazy: only needed when using the camera
        self._mp_hands = mp.solutions.hands
        self._hands = self._mp_hands.Hands(
            static_image_mode=False,
            max_num_hands=1,
            model_complexity=0,  # lighter model, matters on the Pi
            min_detection_confidence=min_detection_confidence,
            min_tracking_confidence=min_tracking_confidence,
        )
        self.last_landmarks = None

    def count(self, bgr_image) -> Optional[int]:
        """Finger count for the most prominent hand, or None if no hand."""
        import cv2
        h, w = bgr_image.shape[:2]
        rgb = cv2.cvtColor(bgr_image, cv2.COLOR_BGR2RGB)
        result = self._hands.process(rgb)
        if not result.multi_hand_landmarks:
            self.last_landmarks = None
            return None
        hand = result.multi_hand_landmarks[0]
        self.last_landmarks = hand
        points = [(lm.x * w, lm.y * h) for lm in hand.landmark]
        return count_fingers(points)

    def close(self) -> None:
        self._hands.close()
