"""Turn-away-and-resume logic (ROS-independent).

The main state machine starts a turn after the robot has stopped and named
the obstacle. The robot turns in place until the front has been clear for
``clear_time`` seconds, then reports DONE so the state machine can hand
driving back to the operator.

There is no odometry, so the turned angle is estimated as speed x time.
The turn is never shorter than ``min_turn`` (so the robot does not stop
while the obstacle is still at the edge of the sensor) and never longer than
``max_turn``: past that the robot is boxed in and reports FAILED.
"""

import math
from dataclasses import dataclass
from enum import Enum
from typing import List, Optional


class EventType(str, Enum):
    TURNING = "turning"      # turn started, ``direction`` is +1 left / -1 right
    DONE = "done"            # front is clear, operator drives again
    FAILED = "failed"        # turned max_turn without finding a clear front
    CANCELLED = "cancelled"  # stopped from outside


@dataclass
class Event:
    type: EventType
    direction: int = 0


class Avoider:
    def __init__(
        self,
        clear_distance: float = 0.40,
        turn_speed: float = 1.0,
        min_turn: float = math.radians(30),
        max_turn: float = math.radians(270),
        clear_time: float = 0.3,
        default_direction: int = 1,
    ):
        if turn_speed <= 0:
            raise ValueError("turn_speed must be > 0")
        if not 0 <= min_turn < max_turn:
            raise ValueError("need 0 <= min_turn < max_turn")
        if default_direction not in (1, -1):
            raise ValueError("default_direction must be 1 (left) or -1 (right)")
        self.clear_distance = clear_distance
        self.turn_speed = turn_speed
        self.min_turn = min_turn
        self.max_turn = max_turn
        self.clear_time = clear_time
        self.default_direction = default_direction

        self.active = False
        self.direction = 0
        self._start_t = 0.0
        self._clear_since: Optional[float] = None

    @property
    def angular_velocity(self) -> float:
        """Command to send now (rad/s), 0 when not turning."""
        return self.direction * self.turn_speed if self.active else 0.0

    def turned(self, t: float) -> float:
        return (t - self._start_t) * self.turn_speed if self.active else 0.0

    def choose_direction(self, left: float, right: float) -> int:
        """Turn toward the side with more room; ties go to the default."""
        if left > right:
            return 1
        if right > left:
            return -1
        return self.default_direction

    def start(self, t: float, left: float = math.inf, right: float = math.inf) -> List[Event]:
        """Begin a turn. Ultrasonic has no side readings: leave left/right at
        inf and the robot turns ``default_direction``."""
        self.active = True
        self.direction = self.choose_direction(left, right)
        self._start_t = t
        self._clear_since = None
        return [Event(EventType.TURNING, self.direction)]

    def _end(self, event_type: EventType) -> List[Event]:
        event = Event(event_type, self.direction)
        self.active = False
        self.direction = 0
        return [event]

    def cancel(self) -> List[Event]:
        return self._end(EventType.CANCELLED) if self.active else []

    def fail(self) -> List[Event]:
        """Stop the turn as FAILED, e.g. the distance sensor went silent."""
        return self._end(EventType.FAILED) if self.active else []

    def tick(self, t: float, front: float) -> List[Event]:
        """Call at the control rate with the latest filtered front distance."""
        if not self.active:
            return []
        if front >= self.clear_distance:
            if self._clear_since is None:
                self._clear_since = t
        else:
            self._clear_since = None

        turned = self.turned(t)
        if (turned >= self.min_turn and self._clear_since is not None
                and t - self._clear_since >= self.clear_time):
            return self._end(EventType.DONE)
        if turned >= self.max_turn:
            return self._end(EventType.FAILED)
        return []
