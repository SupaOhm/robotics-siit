"""Obstacle threshold with hysteresis (ROS-independent).

The robot is blocked once the filtered distance drops to ``stop_distance``,
and clear again only when it rises to ``clear_distance``. The gap between the
two keeps a reading that hovers around one threshold from toggling the state
on every frame.
"""


class ObstacleDetector:
    def __init__(self, stop_distance: float = 0.30, clear_distance: float = 0.40):
        if not 0 < stop_distance < clear_distance:
            raise ValueError("need 0 < stop_distance < clear_distance")
        self.stop_distance = stop_distance
        self.clear_distance = clear_distance
        self.blocked = False

    def update(self, distance: float) -> bool:
        """Feed one filtered distance, return True while blocked."""
        if self.blocked:
            self.blocked = distance < self.clear_distance
        else:
            self.blocked = distance <= self.stop_distance
        return self.blocked

    def reset(self) -> None:
        self.blocked = False
