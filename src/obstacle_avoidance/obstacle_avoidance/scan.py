"""Reduce a LiDAR scan to front / left / right distances (ROS-independent).

The front distance looks along a corridor as wide as the robot, not a cone:
at 0.30 m a +-15 deg cone is only +-8 cm wide, so the CoppeliaSim test
missed obstacles at the robot's shoulders until 0.17 m. Left and right are
cones and only pick the turn direction.

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


def corridor_min(ranges: Sequence[float], angle_min: float, angle_increment: float,
                 half_width: float, front_angle: float = 0.0, min_valid: float = 0.0) -> float:
    """Distance ahead to the closest point within ``half_width`` of the
    robot's centre line. Beams pointing sideways or back are ignored.

    Same no-return rules as ``sector_min``: inf when nothing is in the
    corridor, NaN when there is no usable reading ahead at all.
    """
    closest = math.nan
    for i, r in enumerate(ranges):
        if math.isnan(r) or r < min_valid:
            continue
        a = angle_min + i * angle_increment - front_angle
        if math.cos(a) <= 0:
            continue
        if math.isfinite(r) and abs(r * math.sin(a)) <= half_width:
            ahead = r * math.cos(a)
        else:
            ahead = math.inf  # the beam leaves the corridor before it hits anything
        closest = ahead if math.isnan(closest) else min(closest, ahead)
    return closest


def front_left_right(ranges: Sequence[float], angle_min: float, angle_increment: float,
                     front_angle: float = 0.0, corridor_half_width: float = 0.20,
                     side_half_width: float = math.radians(30), min_valid: float = 0.0):
    """(front, left, right) distances. Front is ``corridor_min``; left and
    right are the closest readings within ``side_half_width`` of +90 and -90
    degrees from the robot's front."""
    def sector(offset):
        return sector_min(ranges, angle_min, angle_increment,
                          front_angle + offset, side_half_width, min_valid)
    front = corridor_min(ranges, angle_min, angle_increment, corridor_half_width,
                         front_angle, min_valid)
    return front, sector(math.pi / 2), sector(-math.pi / 2)
