"""Spoken-password verification state machine (ROS-independent).

A session starts when the main state machine sees a person. Each attempt is
one listening window: the person says the password, a speech engine turns it
into text, and the text is checked. A wrong answer, silence, or unclear
speech each cost one attempt. After ``max_attempts`` failures the session
ends as LOCKED_OUT, which is the signal for the alert / Telegram flow.

If the speech engine itself fails (e.g. no internet) the attempt is not
counted, but after ``max_service_errors`` failures in a row the session is
LOCKED_OUT too, so the operator can decide on Telegram.
"""

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from enum import Enum
from typing import Iterable, List, Tuple

from .normalize import normalize


class EventType(str, Enum):
    STARTED = "started"            # session began, play the password prompt
    WRONG = "wrong"                # heard something, but not the password
    NO_SPEECH = "no_speech"        # nobody spoke in time
    UNCLEAR = "unclear"            # speech heard but could not be transcribed
    SERVICE_ERROR = "service_error"  # speech engine failed, attempt not counted
    GRANTED = "granted"            # correct password, session over
    LOCKED_OUT = "locked_out"      # out of attempts, trigger the alert flow
    CANCELLED = "cancelled"        # stopped from outside (e.g. person left)


MATCH_MODES = ("contains", "exact")

# What the state machine reads on /password/result (docs/interfaces.md)
RESULT_FOR_EVENT = {
    EventType.GRANTED: "granted",
    EventType.LOCKED_OUT: "denied",
    EventType.CANCELLED: "cancelled",
}
# Prompts the password node plays itself on /audio/play
CLIP_FOR_EVENT = {
    EventType.STARTED: "password_prompt",
    EventType.WRONG: "password_wrong",
    EventType.NO_SPEECH: "password_wrong",
    EventType.UNCLEAR: "password_wrong",
    EventType.LOCKED_OUT: "password_denied",
}


@dataclass
class Event:
    type: EventType
    attempts_left: int


def outputs_for(events) -> Tuple[List[str], List[str]]:
    """(results, clips) to publish for one batch of events. The last failure
    plays only "password_denied", not "password_wrong" first."""
    types = [ev.type for ev in events]
    results = [RESULT_FOR_EVENT[t] for t in types if t in RESULT_FOR_EVENT]
    clips = [CLIP_FOR_EVENT[t] for t in types if t in CLIP_FOR_EVENT]
    if EventType.LOCKED_OUT in types:
        clips = [c for c in clips if c != "password_wrong"]
    return results, clips


def hash_password(normalized: str, salt: str) -> str:
    """Hex SHA-256 of ``salt + normalized``. Normalize the text first."""
    return hashlib.sha256((salt + normalized).encode("utf-8")).hexdigest()


def make_salt() -> str:
    return secrets.token_hex(8)


def make_stored(normalized: str, salt: str = "") -> str:
    """The single ROBOT_PASSWORD_HASH value: "<length>:<salt>:<sha256 hex>".
    Length, salt and hash travel together, so they can't get out of step."""
    salt = salt or make_salt()
    return "%d:%s:%s" % (len(normalized), salt, hash_password(normalized, salt))


def parse_stored(value: str) -> Tuple[str, str, int]:
    """(hash, salt, length) from a make_stored() value. ValueError if malformed."""
    parts = value.strip().split(":")
    if (len(parts) != 3 or not parts[0].isdigit() or int(parts[0]) < 1
            or not parts[1] or len(parts[2]) != 64):
        raise ValueError("ROBOT_PASSWORD_HASH must look like <length>:<salt>:<64 hex "
                         "chars>; print a new one with make_password_hash")
    return parts[2], parts[1], int(parts[0])


class PasswordVerifier:
    def __init__(
        self,
        password_hash: str,
        salt: str,
        password_chars: int,
        max_attempts: int = 3,
        match_mode: str = "exact",
        max_service_errors: int = 3,
    ):
        if password_chars < 1:
            raise ValueError("password_chars must be >= 1")
        if max_attempts < 1:
            raise ValueError("max_attempts must be >= 1")
        if match_mode not in MATCH_MODES:
            raise ValueError("match_mode must be one of %s" % (MATCH_MODES,))
        if max_service_errors < 1:
            raise ValueError("max_service_errors must be >= 1")
        self._hash = password_hash.lower()
        self._salt = salt
        self.password_chars = password_chars
        self.max_attempts = max_attempts
        self.match_mode = match_mode
        self.max_service_errors = max_service_errors

        self.active = False
        self.attempts_used = 0
        self._service_errors = 0

    @property
    def attempts_left(self) -> int:
        return self.max_attempts - self.attempts_used

    def _event(self, event_type: EventType) -> Event:
        return Event(event_type, self.attempts_left)

    def _end(self, event_type: EventType) -> Event:
        self.active = False
        return self._event(event_type)

    def _fail_attempt(self, event_type: EventType) -> List[Event]:
        self.attempts_used += 1
        events = [self._event(event_type)]
        if self.attempts_left <= 0:
            events.append(self._end(EventType.LOCKED_OUT))
        return events

    def _is_hit(self, normalized: str) -> bool:
        return hmac.compare_digest(hash_password(normalized, self._salt), self._hash)

    def matches(self, text: str) -> bool:
        """True if ``text`` is (or, in contains mode, includes) the password."""
        heard = normalize(text)
        if self.match_mode == "exact":
            return self._is_hit(heard)
        n = self.password_chars
        return any(self._is_hit(heard[i:i + n]) for i in range(len(heard) - n + 1))

    def start(self) -> List[Event]:
        """Begin a new session (resets attempts)."""
        self.active = True
        self.attempts_used = 0
        self._service_errors = 0
        return [self._event(EventType.STARTED)]

    def cancel(self) -> List[Event]:
        if not self.active:
            return []
        return [self._end(EventType.CANCELLED)]

    def submit(self, candidates: Iterable[str]) -> List[Event]:
        """Check one attempt. ``candidates`` are the engine's transcriptions
        of the same utterance; any one matching is enough. Empty = unclear."""
        if not self.active:
            return []
        self._service_errors = 0
        candidates = [c for c in candidates if c and c.strip()]
        if not candidates:
            return self._fail_attempt(EventType.UNCLEAR)
        if any(self.matches(c) for c in candidates):
            return [self._end(EventType.GRANTED)]
        return self._fail_attempt(EventType.WRONG)

    def no_speech(self) -> List[Event]:
        if not self.active:
            return []
        self._service_errors = 0
        return self._fail_attempt(EventType.NO_SPEECH)

    def handle(self, result) -> List[Event]:
        """Events for one listen result (speech.ListenResult: kind is
        "speech", "no_speech" or "error")."""
        if result.kind == "no_speech":
            return self.no_speech()
        if result.kind == "error":
            return self.service_error()
        return self.submit(result.candidates)

    def service_error(self) -> List[Event]:
        if not self.active:
            return []
        self._service_errors += 1
        events = [self._event(EventType.SERVICE_ERROR)]
        if self._service_errors >= self.max_service_errors:
            events.append(self._end(EventType.LOCKED_OUT))
        return events
