import math

import pytest

from obstacle_avoidance.scan import corridor_min, front_left_right, sector_min

STEP = math.radians(1)


def scan(points, default=5.0):
    """360 beams from -180 deg, one per degree; ``points`` maps deg -> range."""
    ranges = [default] * 360
    for deg, r in points.items():
        ranges[deg + 180] = r
    return ranges, -math.pi, STEP


def ahead(r, deg):
    return r * math.cos(math.radians(deg))


def test_front_is_closest_point_in_the_corridor():
    ranges, a0, inc = scan({0: 0.8, 10: 0.5, 60: 0.3})
    front, _, _ = front_left_right(ranges, a0, inc, corridor_half_width=0.20)
    assert front == pytest.approx(ahead(0.5, 10))  # 60 deg, 0.3 m is 0.26 m to the side


def test_obstacle_at_the_shoulder_is_seen():
    """The CoppeliaSim case: 25 deg is outside a +-15 deg cone but in the robot's path."""
    ranges, a0, inc = scan({25: 0.3})
    front, _, _ = front_left_right(ranges, a0, inc, corridor_half_width=0.20)
    assert front == pytest.approx(ahead(0.3, 25))


def test_beam_leaving_the_corridor_counts_as_clear():
    ranges, a0, inc = scan({}, default=math.inf)
    ranges[45 + 180] = 2.0  # 1.4 m to the side
    assert corridor_min(ranges, a0, inc, 0.20) == math.inf


def test_left_is_positive_angle():
    ranges, a0, inc = scan({90: 0.4, -90: 2.0})
    _, left, right = front_left_right(ranges, a0, inc)
    assert left == 0.4
    assert right == 2.0


def test_front_angle_for_backward_lidar():
    ranges, a0, inc = scan({179: 0.3, 0: 3.0})
    front, _, _ = front_left_right(ranges, a0, inc, front_angle=math.pi)
    assert front == pytest.approx(ahead(0.3, 1))


def test_no_finite_reading_gives_inf():
    ranges, a0, inc = scan({}, default=math.inf)
    assert sector_min(ranges, a0, inc, 0.0, math.radians(15)) == math.inf


def test_zero_beams_are_skipped():
    """The YDLIDAR driver leaves beams with no return at 0."""
    ranges, a0, inc = scan({0: 0.0, 5: 0.0, 10: 0.7})
    front, _, _ = front_left_right(ranges, a0, inc, min_valid=0.05)
    assert front == pytest.approx(ahead(0.7, 10))


def test_no_usable_reading_is_nan():
    ranges, a0, inc = scan({}, default=0.0)
    assert math.isnan(sector_min(ranges, a0, inc, 0.0, math.radians(15), 0.05))
    assert math.isnan(corridor_min(ranges, a0, inc, 0.20, min_valid=0.05))
