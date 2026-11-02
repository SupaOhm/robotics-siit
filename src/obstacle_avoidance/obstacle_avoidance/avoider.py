"""Turn-away-and-resume logic (ROS-independent).

The main state machine starts a turn after the robot has stopped and named
the obstacle. The A1 has mecanum wheels, so the robot turns in place until
the corridor ahead has been clear for ``clear_time`` seconds, then reports
DONE so the state machine can hand driving back to the operator.

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
    FAILED = "failed"        # boxed in, or the sensor went silent
    CANCELLED = "cancelled"  # stopped from outside


@dataclass
class Event:
    type: EventType
    direction: int = 0


def _wrap(angle: float) -> float:
    return math.atan2(math.sin(angle), math.cos(angle))


class Avoider:
    """Turns in place. The turned angle comes from the measured yaw (IMU)
    passed to tick(), or from speed x time when there is none. Mecanum wheels
    slip when turning in place, so speed x time can run ahead of the real
    turn.

    Speed x time still caps the turn: once it reaches ``max_turn`` the turn
    FAILS whatever the IMU says, so a robot that doesn't turn (stuck, or a
    base that can't turn in place) gives up after max_turn / turn_speed."""

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
        self.turned_angle = 0.0
        self._start_t = 0.0
        self._t = 0.0
        self._yaw: Optional[float] = None
        self._clear_since: Optional[float] = None

    @property
    def angular_velocity(self) -> float:
        """Command to send now (rad/s), 0 when not turning."""
        return self.direction * self.turn_speed if self.active else 0.0

    def estimated_turn(self, t: float) -> float:
        """Speed x time since start (rad)."""
        return (t - self._start_t) * self.turn_speed if self.active else 0.0

    def choose_direction(self, left: float, right: float) -> int:
        """Turn toward the side with more room; ties go to the default."""
        if left > right:
            return 1
        if right > left:
            return -1
        return self.default_direction

    def start(self, t: float, left: float = math.inf, right: float = math.inf,
              yaw: Optional[float] = None) -> List[Event]:
        """Begin a turn. Ultrasonic has no side readings: leave left/right at
        inf and the robot turns ``default_direction``."""
        self.active = True
        self.direction = self.choose_direction(left, right)
        self.turned_angle = 0.0
        self._start_t = self._t = t
        self._yaw = yaw
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

    def tick(self, t: float, front: float, yaw: Optional[float] = None) -> List[Event]:
        """Call at the control rate with the latest filtered front distance
        and, if there is an IMU, the current yaw (rad)."""
        if not self.active:
            return []
        if yaw is not None and self._yaw is not None:
            gained = _wrap(yaw - self._yaw)
        else:
            gained = self.angular_velocity * (t - self._t)
        self.turned_angle += self.direction * gained
        if yaw is not None:
            self._yaw = yaw
        self._t = t

        if front >= self.clear_distance:
            if self._clear_since is None:
                self._clear_since = t
        else:
            self._clear_since = None

        if (self.turned_angle >= self.min_turn and self._clear_since is not None
                and t - self._clear_since >= self.clear_time):
            return self._end(EventType.DONE)
        if self.turned_angle >= self.max_turn or self.estimated_turn(t) >= self.max_turn:
            return self._end(EventType.FAILED)
        return []
