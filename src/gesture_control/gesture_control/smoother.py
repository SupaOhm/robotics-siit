"""Per-frame raw word -> stable word. Plain Python; time is passed in.

- A new word must be seen ``confirm_frames`` frames in a row before it
  replaces the current one. ``back`` needs ``back_confirm_frames``, because
  holding ``back`` for 1 s is the operator override and Resume (D11).
- No hand (raw ``None``) holds the current word for ``dropout_hold_s``, so a
  single missed detection doesn't jerk the robot, then becomes ``none``.
  The hold must stay below the robot's 0.5 s gesture timeout (D4).
"""

from typing import Optional

from .classifier import WORDS

ROBOT_TIMEOUT_S = 0.5  # state machine stops the robot after this much silence (D4)


class WordSmoother:
    def __init__(self, confirm_frames: int = 3, back_confirm_frames: int = 6,
                 dropout_hold_s: float = 0.3):
        if confirm_frames < 1:
            raise ValueError("confirm_frames must be >= 1")
        if back_confirm_frames < confirm_frames:
            raise ValueError("back_confirm_frames must be >= confirm_frames")
        if not 0 <= dropout_hold_s < ROBOT_TIMEOUT_S:
            raise ValueError("dropout_hold_s must be in [0, %.1f)" % ROBOT_TIMEOUT_S)
        self.confirm_frames = confirm_frames
        self.back_confirm_frames = back_confirm_frames
        self.dropout_hold_s = dropout_hold_s
        self.reset()

    def reset(self) -> None:
        self.current = "none"
        self._candidate: Optional[str] = None
        self._count = 0
        self._last_hand: Optional[float] = None

    @property
    def last_hand(self) -> Optional[float]:
        """Time of the last frame with a hand, or None."""
        return self._last_hand

    def _needed(self, word: str) -> int:
        return self.back_confirm_frames if word == "back" else self.confirm_frames

    def update(self, raw: Optional[str], now: float) -> str:
        """Feed one frame's raw word (``None`` = no hand). Returns the stable word."""
        if raw is None:
            self._candidate, self._count = None, 0
            if self._last_hand is None or now - self._last_hand >= self.dropout_hold_s:
                self.current = "none"
            return self.current

        if raw not in WORDS:
            raise ValueError("unknown word: %r" % raw)
        self._last_hand = now
        if raw == self.current:
            self._candidate, self._count = None, 0
            return self.current
        if raw == self._candidate:
            self._count += 1
        else:
            self._candidate, self._count = raw, 1
        if self._count >= self._needed(raw):
            self.current = raw
            self._candidate, self._count = None, 0
        return self.current
