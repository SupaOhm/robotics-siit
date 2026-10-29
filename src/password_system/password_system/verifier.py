"""Password verification state machine (ROS-independent).

A session is started when the main state machine sees a person. The person
enters a fixed-length sequence of gesture tokens (finger counts "1".."5").
A full wrong sequence, or no input for ``input_timeout`` seconds, costs one
attempt. After ``max_attempts`` failures the session ends as LOCKED_OUT,
which is the signal for the alert / Telegram flow.
"""

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from enum import Enum
from typing import List, Optional


class EventType(str, Enum):
    STARTED = "started"            # session began, play the password prompt
    TOKEN = "token"                # one token accepted (do not reveal its value)
    WRONG = "wrong"                # full sequence entered, but wrong
    ATTEMPT_TIMEOUT = "attempt_timeout"  # no input for too long, counts as wrong
    GRANTED = "granted"            # correct password, session over
    LOCKED_OUT = "locked_out"      # out of attempts, trigger the alert flow
    CANCELLED = "cancelled"        # stopped from outside (e.g. person left)


TERMINAL_EVENTS = (EventType.GRANTED, EventType.LOCKED_OUT, EventType.CANCELLED)


@dataclass
class Event:
    type: EventType
    attempts_left: int
    tokens_entered: int
    password_length: int

    def to_dict(self) -> dict:
        return {
            "type": self.type.value,
            "attempts_left": self.attempts_left,
            "tokens_entered": self.tokens_entered,
            "password_length": self.password_length,
        }


def hash_password(password: str, salt: str) -> str:
    """Return the hex SHA-256 of ``salt + password``."""
    return hashlib.sha256((salt + password).encode("utf-8")).hexdigest()


def make_salt() -> str:
    return secrets.token_hex(8)


class PasswordVerifier:
    def __init__(
        self,
        password_hash: str,
        salt: str,
        password_length: int,
        max_attempts: int = 3,
        input_timeout: float = 15.0,
    ):
        if password_length < 1:
            raise ValueError("password_length must be >= 1")
        if max_attempts < 1:
            raise ValueError("max_attempts must be >= 1")
        self._hash = password_hash.lower()
        self._salt = salt
        self.password_length = password_length
        self.max_attempts = max_attempts
        self.input_timeout = input_timeout

        self.active = False
        self.attempts_used = 0
        self._entered: List[str] = []
        self._last_input: Optional[float] = None

    @property
    def attempts_left(self) -> int:
        return self.max_attempts - self.attempts_used

    @property
    def tokens_entered(self) -> int:
        return len(self._entered)

    def _event(self, event_type: EventType) -> Event:
        return Event(event_type, self.attempts_left, self.tokens_entered,
                     self.password_length)

    def _end(self, event_type: EventType) -> Event:
        self.active = False
        self._entered.clear()
        return self._event(event_type)

    def _fail_attempt(self, event_type: EventType, now: float) -> List[Event]:
        self.attempts_used += 1
        self._entered.clear()
        self._last_input = now
        events = [self._event(event_type)]
        if self.attempts_left <= 0:
            events.append(self._end(EventType.LOCKED_OUT))
        return events

    def start(self, now: float) -> List[Event]:
        """Begin a new session (resets attempts)."""
        self.active = True
        self.attempts_used = 0
        self._entered.clear()
        self._last_input = now
        return [self._event(EventType.STARTED)]

    def cancel(self) -> List[Event]:
        if not self.active:
            return []
        return [self._end(EventType.CANCELLED)]

    def feed(self, token: str, now: float) -> List[Event]:
        """Add one accepted gesture token. Ignored when no session is active."""
        if not self.active:
            return []
        self._entered.append(str(token))
        self._last_input = now
        if len(self._entered) < self.password_length:
            return [self._event(EventType.TOKEN)]

        candidate = "".join(self._entered)
        if hmac.compare_digest(hash_password(candidate, self._salt), self._hash):
            return [self._event(EventType.TOKEN), self._end(EventType.GRANTED)]
        return [self._event(EventType.TOKEN)] + self._fail_attempt(EventType.WRONG, now)

    def tick(self, now: float) -> List[Event]:
        """Call periodically; handles the per-attempt input timeout."""
        if not self.active or self.input_timeout <= 0 or self._last_input is None:
            return []
        if now - self._last_input >= self.input_timeout:
            return self._fail_attempt(EventType.ATTEMPT_TIMEOUT, now)
        return []
