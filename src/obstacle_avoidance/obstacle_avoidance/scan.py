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
               center: float, half_width: float) -> float:
    """Closest finite reading within ``half_width`` of ``center``.
    Returns inf when the sector has no finite reading."""
    closest = math.inf
    for i, r in enumerate(ranges):
        if not math.isfinite(r):
            continue
        if abs(_wrap(angle_min + i * angle_increment - center)) <= half_width:
            closest = min(closest, r)
    return closest


def front_left_right(ranges: Sequence[float], angle_min: float, angle_increment: float,
                     front_angle: float = 0.0, front_half_width: float = math.radians(15),
                     side_half_width: float = math.radians(30)):
    """(front, left, right) closest distances. Left and right are centred at
    +90 and -90 degrees from the robot's front."""
    def sector(offset, half_width):
        return sector_min(ranges, angle_min, angle_increment,
                          front_angle + offset, half_width)
    return (sector(0.0, front_half_width),
            sector(math.pi / 2, side_half_width),
            sector(-math.pi / 2, side_half_width))
