"""Reduce a LiDAR scan to front / left / right distances (ROS-independent).

Angles follow ROS: radians, 0 = the LiDAR's forward axis, positive = counter-
clockwise (to the left). ``front_angle`` corrects for a LiDAR mounted turned
on the robot (e.g. pi if its cable side faces forward).
"""

import math
from typing import Sequence


def _wrap(angle: float) -> float:
    return math.atan2(math.sin(angle), math.cos(angle))


def sector_min(ranges: Sequence[float], angle_min: float, angle_increment: float,
               center: float, half_width: float, min_valid: float = 0.0) -> float:
    """Closest reading within ``half_width`` of ``center``.

    Readings below ``min_valid`` (and NaN) are beams with no return: the
    YDLIDAR driver leaves those at 0. They are skipped. Returns inf when the
    sector only has inf readings (nothing in range), and NaN when it has no
    usable reading at all.
    """
    closest = math.nan
    for i, r in enumerate(ranges):
        if math.isnan(r) or r < min_valid:
            continue
        if abs(_wrap(angle_min + i * angle_increment - center)) <= half_width:
            closest = r if math.isnan(closest) else min(closest, r)
    return closest


def front_left_right(ranges: Sequence[float], angle_min: float, angle_increment: float,
                     front_angle: float = 0.0, front_half_width: float = math.radians(15),
                     side_half_width: float = math.radians(30), min_valid: float = 0.0):
    """(front, left, right) closest distances. Left and right are centred at
    +90 and -90 degrees from the robot's front."""
    def sector(offset, half_width):
        return sector_min(ranges, angle_min, angle_increment,
                          front_angle + offset, half_width, min_valid)
    return (sector(0.0, front_half_width),
            sector(math.pi / 2, side_half_width),
            sector(-math.pi / 2, side_half_width))
