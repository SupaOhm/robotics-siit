"""Noise filter for distance readings (ROS-independent).

Both sensors give noisy single readings: an ultrasonic echo can bounce off
the floor, and a LiDAR beam can miss a thin chair leg. The filter keeps the
median of the last ``window`` readings, so one bad reading does not stop or
start the robot. Rules for each raw reading:

- NaN, or closer than ``min_range``: dropped as a sensor glitch
- inf, or farther than ``max_range``: counted as ``max_range`` (nothing near)
"""

import math
import statistics
from collections import deque
from typing import Optional


class RangeFilter:
    def __init__(self, window: int = 5, min_range: float = 0.02, max_range: float = 4.0):
        if window < 1:
            raise ValueError("window must be >= 1")
        if not 0 <= min_range < max_range:
            raise ValueError("need 0 <= min_range < max_range")
        self.min_range = min_range
        self.max_range = max_range
        self._readings = deque(maxlen=window)

    def update(self, reading: float) -> Optional[float]:
        """Add one raw reading, return the filtered distance (None until the
        first valid reading)."""
        if not math.isnan(reading) and reading >= self.min_range:
            self._readings.append(min(reading, self.max_range))
        return self.value

    @property
    def value(self) -> Optional[float]:
        if not self._readings:
            return None
        return statistics.median(self._readings)

    def reset(self) -> None:
        self._readings.clear()
