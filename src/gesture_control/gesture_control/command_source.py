"""Thread-safe holder for the latest word, plus the per-frame pipeline.

The camera thread writes a word per frame; the 10 Hz ROS timer reads it.
If no frame result arrived within ``stale_s`` (camera or MediaPipe stalled),
the reader gets ``none``, so the topic never goes silent and never repeats
a stale drive word (D4).
"""

import threading
from typing import Optional, Sequence, Tuple

from .classifier import WORDS, Classification, GestureClassifier, Point
from .smoother import ROBOT_TIMEOUT_S, WordSmoother


class LatestWord:
    def __init__(self, stale_s: float = 0.3):
        if not 0 < stale_s < ROBOT_TIMEOUT_S:
            raise ValueError("stale_s must be in (0, %.1f)" % ROBOT_TIMEOUT_S)
        self.stale_s = stale_s
        self._lock = threading.Lock()
        self._word = "none"
        self._stamp: Optional[float] = None

    def set(self, word: str, stamp: float) -> None:
        if word not in WORDS:
            raise ValueError("unknown word: %r" % word)
        with self._lock:
            self._word, self._stamp = word, stamp

    def get(self, now: float) -> str:
        with self._lock:
            if self._stamp is None or now - self._stamp > self.stale_s:
                return "none"
            return self._word


class GesturePipeline:
    """Classifier + smoother for one frame. ``landmarks`` None = no hand.

    After ``step``, ``last_stamp`` is the time to store with the word in
    ``LatestWord``: the frame time, except while the smoother holds a word
    through a dropout, when it is the time of the last frame with a hand.
    So the dropout hold and ``stale_s`` overlap instead of adding up: a held
    drive word goes stale ``stale_s`` after the hand was last seen.
    """

    def __init__(self, classifier: Optional[GestureClassifier] = None,
                 smoother: Optional[WordSmoother] = None):
        self.classifier = classifier or GestureClassifier()
        self.smoother = smoother or WordSmoother()
        self.last_stamp: Optional[float] = None

    def reset(self) -> None:
        """Forget all state. Call after a camera or tracker gap, so the first
        frame after it must pass confirm_frames again."""
        self.classifier.prev = None
        self.smoother.reset()
        self.last_stamp = None

    def step(self, landmarks: Optional[Sequence[Point]], now: float,
             aspect: float = 1.0) -> Tuple[str, Optional[Classification]]:
        result = self.classifier(landmarks, aspect)
        word = self.smoother.update(result.word if result else None, now)
        stamp = now
        if result is None and word != "none" and self.smoother.last_hand is not None:
            stamp = self.smoother.last_hand  # held through a dropout
        self.last_stamp = stamp
        return word, result
