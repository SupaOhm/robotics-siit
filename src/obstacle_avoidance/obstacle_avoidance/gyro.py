"""Turned angle from the IMU gyro (ROS-independent)."""

from typing import Optional


class GyroYaw:
    """Integrates gyro z into a yaw (rad). Only differences matter, so it
    starts at 0 and drift over one turn is small.

    ``yaw(now)`` is None before the first reading and while the gyro has
    been silent for more than ``timeout`` seconds. A turn then falls back to
    speed x time instead of reading a yaw that has stopped changing."""

    def __init__(self, timeout: float = 0.2, max_gap: float = 0.5):
        self.timeout = timeout
        self.max_gap = max_gap
        self._yaw = 0.0
        self._stamp: Optional[float] = None
        self._received: Optional[float] = None

    def update(self, stamp: float, rate: float, now: float) -> None:
        """One reading: ``rate`` (rad/s) measured at ``stamp`` (the message
        header), received at ``now`` (the node clock). A gap longer than
        ``max_gap`` between stamps is skipped, not integrated."""
        if self._stamp is not None and 0 < stamp - self._stamp < self.max_gap:
            self._yaw += rate * (stamp - self._stamp)
        self._stamp = stamp
        self._received = now

    def yaw(self, now: float) -> Optional[float]:
        if self._received is None or now - self._received > self.timeout:
            return None
        return self._yaw
