"""Audio of the failed answers in one password session (D32).

Kept in memory and handed over only when the session ends as denied, so the
operator can hear them on Telegram. A correct answer contains the password,
so a granted session drops everything and nothing is ever written.
"""

from typing import List

from .verifier import EventType

FAILED = (EventType.WRONG, EventType.UNCLEAR)


class AttemptRecordings:
    def __init__(self):
        self.clips: List[bytes] = []

    def clear(self) -> None:
        """A new session started, or the old one was cancelled."""
        self.clips = []

    def handle(self, wav: bytes, events) -> List[bytes]:
        """``wav`` is the answer that produced ``events`` (b"" for silence or
        an engine failure). Returns the clips to send when the session is
        denied, else []."""
        types = [ev.type for ev in events]
        if wav and any(t in FAILED for t in types):
            self.clips.append(wav)
        if EventType.LOCKED_OUT in types:
            clips, self.clips = self.clips, []
            return clips
        if EventType.GRANTED in types:
            self.clear()
        return []
