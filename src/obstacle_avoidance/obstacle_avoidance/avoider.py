"""Turn-away-and-resume logic (ROS-independent).

The main state machine starts a turn after the robot has stopped and named
the obstacle. The robot turns until the corridor ahead has been clear for
``clear_time`` seconds, then reports DONE so the state machine can hand
driving back to the operator. Two bases, picked by ``drive_type``:

- ``Avoider`` (diff): turns in place.
- ``AckermannAvoider`` (ackermann, the A1): can't turn in place, so it
  backs up on full lock and drives forward on full lock, like a three-point
  turn.

Both never turn less than ``min_turn`` (so the robot does not stop while the
obstacle is still at the edge of the sensor) or more than ``max_turn``: past
that the robot is boxed in and reports FAILED. ``command`` is the
(linear m/s, angular rad/s) to send while ``active``.
"""

import math
from dataclasses import dataclass
from enum import Enum
from typing import Callable, List, Optional, Tuple


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


def choose_direction(left: float, right: float, default: int) -> int:
    """Turn toward the side with more room; ties go to the default."""
    if left > right:
        return 1
    if right > left:
        return -1
    return default


class Avoider:
    """Turns in place. There is no odometry, so the turned angle is
    estimated as speed x time."""

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

    @property
    def command(self) -> Tuple[float, float]:
        return 0.0, self.angular_velocity

    def turned(self, t: float) -> float:
        return (t - self._start_t) * self.turn_speed if self.active else 0.0

    def choose_direction(self, left: float, right: float) -> int:
        return choose_direction(left, right, self.default_direction)

    def start(self, t: float, left: float = math.inf, right: float = math.inf,
              yaw: Optional[float] = None) -> List[Event]:
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

    def tick(self, t: float, front: float, rear: float = math.inf,
             yaw: Optional[float] = None) -> List[Event]:
        """Call at the control rate with the latest filtered front distance.
        ``rear`` and ``yaw`` are only used by AckermannAvoider."""
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


class AckermannAvoider:
    """Three-point turn for a car-like base (the A1 can't turn in place).

    BACKING: reverse on full lock, so the nose swings toward ``direction``.
    It ends after ``back_turn`` of heading, ``max_reverse`` of distance, or
    when the rear closes to ``rear_clear``.
    ARC: drive forward on full lock the same way round. DONE once the
    corridor ahead is clear for ``clear_time`` and the robot has turned at
    least ``min_turn``. If the front closes to ``arc_min_front`` it backs up
    again; after ``max_cycles`` backing phases it reports FAILED.

    The turned angle comes from the measured yaw (IMU) passed to tick(), or
    from integrating the commands when there is none.
    """

    BACKING = "backing"
    ARC = "arc"

    def __init__(
        self,
        clear_distance: float = 0.40,
        speed: float = 0.15,
        wheelbase: float = 0.16,
        max_steer: float = math.radians(30),
        back_turn: float = math.radians(30),
        max_reverse: float = 0.25,
        rear_clear: float = 0.20,
        arc_min_front: float = 0.20,
        min_turn: float = math.radians(30),
        max_turn: float = math.radians(270),
        clear_time: float = 0.3,
        max_cycles: int = 3,
        default_direction: int = 1,
    ):
        if speed <= 0 or wheelbase <= 0:
            raise ValueError("speed and wheelbase must be > 0")
        if not 0 < max_steer < math.pi / 2:
            raise ValueError("max_steer must be between 0 and 90 degrees")
        if not 0 <= min_turn < max_turn:
            raise ValueError("need 0 <= min_turn < max_turn")
        if max_cycles < 1:
            raise ValueError("max_cycles must be >= 1")
        if default_direction not in (1, -1):
            raise ValueError("default_direction must be 1 (left) or -1 (right)")
        self.clear_distance = clear_distance
        self.speed = speed
        self.yaw_rate = speed * math.tan(max_steer) / wheelbase  # at full lock
        self.back_turn = back_turn
        self.max_reverse = max_reverse
        self.rear_clear = rear_clear
        self.arc_min_front = arc_min_front
        self.min_turn = min_turn
        self.max_turn = max_turn
        self.clear_time = clear_time
        self.max_cycles = max_cycles
        self.default_direction = default_direction

        self.active = False
        self.direction = 0
        self.phase: Optional[str] = None
        self.cycles = 0
        self.turned_angle = 0.0
        self._t = 0.0
        self._yaw: Optional[float] = None
        self._phase_turn = 0.0
        self._phase_dist = 0.0
        self._clear_since: Optional[float] = None

    @property
    def command(self) -> Tuple[float, float]:
        if not self.active:
            return 0.0, 0.0
        linear = -self.speed if self.phase == self.BACKING else self.speed
        return linear, self.direction * self.yaw_rate

    def choose_direction(self, left: float, right: float) -> int:
        return choose_direction(left, right, self.default_direction)

    def start(self, t: float, left: float = math.inf, right: float = math.inf,
              yaw: Optional[float] = None) -> List[Event]:
        self.active = True
        self.direction = self.choose_direction(left, right)
        self.cycles = 0
        self.turned_angle = 0.0
        self._t = t
        self._yaw = yaw
        self._enter(self.BACKING)
        return [Event(EventType.TURNING, self.direction)]

    def _enter(self, phase: str) -> None:
        if phase == self.BACKING:
            self.cycles += 1
        self.phase = phase
        self._phase_turn = 0.0
        self._phase_dist = 0.0
        self._clear_since = None

    def _end(self, event_type: EventType) -> List[Event]:
        event = Event(event_type, self.direction)
        self.active = False
        self.direction = 0
        self.phase = None
        return [event]

    def cancel(self) -> List[Event]:
        return self._end(EventType.CANCELLED) if self.active else []

    def fail(self) -> List[Event]:
        return self._end(EventType.FAILED) if self.active else []

    def _advance(self, t: float, yaw: Optional[float]) -> None:
        dt = t - self._t
        linear, angular = self.command
        if yaw is not None and self._yaw is not None:
            dyaw = _wrap(yaw - self._yaw)
        else:
            dyaw = angular * dt
        if yaw is not None:
            self._yaw = yaw
        gained = self.direction * dyaw
        self.turned_angle += gained
        self._phase_turn += gained
        self._phase_dist += abs(linear) * dt
        self._t = t

    def tick(self, t: float, front: float, rear: float = math.inf,
             yaw: Optional[float] = None) -> List[Event]:
        """Call at the control rate with the filtered front and rear corridor
        distances and, if there is an IMU, the current yaw (rad)."""
        if not self.active:
            return []
        self._advance(t, yaw)

        if self.phase == self.BACKING:
            if (self._phase_turn >= self.back_turn or self._phase_dist >= self.max_reverse
                    or rear < self.rear_clear):
                self._enter(self.ARC)
            return []

        if front >= self.clear_distance:
            if self._clear_since is None:
                self._clear_since = t
        else:
            self._clear_since = None
        if (self.turned_angle >= self.min_turn and self._clear_since is not None
                and t - self._clear_since >= self.clear_time):
            return self._end(EventType.DONE)
        if self.turned_angle >= self.max_turn:
            return self._end(EventType.FAILED)
        if front < self.arc_min_front:
            if self.cycles >= self.max_cycles:
                return self._end(EventType.FAILED)
            self._enter(self.BACKING)
        return []


def make_avoider(param: Callable[[str], object]):
    """The avoider that ``drive_type`` names. ``param(name)`` returns a value
    from config/avoidance.yaml (the node and tools/sim_avoidance.py share this)."""
    drive_type = param("drive_type")
    common = dict(
        clear_distance=float(param("clear_distance")),
        min_turn=math.radians(float(param("min_turn_deg"))),
        max_turn=math.radians(float(param("max_turn_deg"))),
        clear_time=float(param("clear_time")),
        default_direction=int(param("default_direction")),
    )
    if drive_type == "diff":
        return Avoider(turn_speed=float(param("turn_speed")), **common)
    if drive_type == "ackermann":
        return AckermannAvoider(
            speed=float(param("avoid_speed")),
            wheelbase=float(param("wheelbase")),
            max_steer=math.radians(float(param("max_steer_deg"))),
            back_turn=math.radians(float(param("back_turn_deg"))),
            max_reverse=float(param("max_reverse")),
            rear_clear=float(param("rear_clear")),
            arc_min_front=float(param("arc_min_front")),
            max_cycles=int(param("max_cycles")),
            **common)
    raise ValueError("unknown drive_type: %s" % drive_type)
