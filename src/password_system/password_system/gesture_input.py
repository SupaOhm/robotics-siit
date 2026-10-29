"""Turns noisy per-frame finger counts into deliberate password tokens.

A token is accepted only after the same finger count is held steady for
``hold_time`` seconds. To enter the same digit twice in a row, the user must
"release" first: show a fist or take the hand away for ``release_time``
seconds. Switching directly to a different digit needs no release.
Short detection dropouts (shorter than ``release_time``) are ignored.
"""

from typing import Iterable, Optional, Tuple

DEFAULT_TOKENS = ("1", "2", "3", "4", "5")


class GestureDebouncer:
    def __init__(
        self,
        hold_time: float = 0.8,
        release_time: float = 0.4,
        valid_tokens: Iterable[str] = DEFAULT_TOKENS,
    ):
        self.hold_time = hold_time
        self.release_time = release_time
        self.valid_tokens = frozenset(str(t) for t in valid_tokens)
        self.reset()

    def reset(self) -> None:
        self._candidate: Optional[str] = None
        self._candidate_since = 0.0
        self._none_since: Optional[float] = None
        self._last_emitted: Optional[str] = None
        self._released = True

    def update(self, raw, now: float) -> Optional[str]:
        """Feed one frame's reading (finger count, token string or None).

        Returns the accepted token on the frame it is accepted, else None.
        """
        token = None if raw is None else str(raw)
        if token not in self.valid_tokens:
            # No hand, fist ("0") or anything unknown acts as a separator.
            if self._none_since is None:
                self._none_since = now
            if now - self._none_since >= self.release_time:
                self._released = True
                self._candidate = None
            return None

        self._none_since = None
        if token != self._candidate:
            self._candidate = token
            self._candidate_since = now
            return None

        held = now - self._candidate_since >= self.hold_time
        if held and (self._released or token != self._last_emitted):
            self._last_emitted = token
            self._released = False
            return token
        return None

    def progress(self, now: float) -> Tuple[Optional[str], float]:
        """(candidate token, hold fraction 0..1) for on-screen feedback."""
        if self._candidate is None:
            return None, 0.0
        if not self._released and self._candidate == self._last_emitted:
            return self._candidate, 0.0
        frac = (now - self._candidate_since) / self.hold_time if self.hold_time > 0 else 1.0
        return self._candidate, max(0.0, min(1.0, frac))
