import math

from obstacle_avoidance.scan import front_left_right, sector_min

STEP = math.radians(1)


def scan(points, default=5.0):
    """360 beams from -180 deg, one per degree; ``points`` maps deg -> range."""
    ranges = [default] * 360
    for deg, r in points.items():
        ranges[deg + 180] = r
    return ranges, -math.pi, STEP


def test_front_sector_picks_closest():
    ranges, a0, inc = scan({0: 0.8, 10: 0.5, 40: 0.1})
    front, _, _ = front_left_right(ranges, a0, inc)
    assert front == 0.5


def test_left_is_positive_angle():
    ranges, a0, inc = scan({90: 0.4, -90: 2.0})
    _, left, right = front_left_right(ranges, a0, inc)
    assert left == 0.4
    assert right == 2.0


def test_front_angle_for_backward_lidar():
    ranges, a0, inc = scan({179: 0.3, 0: 3.0})
    front, _, _ = front_left_right(ranges, a0, inc, front_angle=math.pi)
    assert front == 0.3


def test_no_finite_reading_gives_inf():
    ranges, a0, inc = scan({}, default=math.inf)
    assert sector_min(ranges, a0, inc, 0.0, math.radians(15)) == math.inf


def test_zero_beams_are_skipped():
    """The YDLIDAR driver leaves beams with no return at 0."""
    ranges, a0, inc = scan({0: 0.0, 5: 0.0, 10: 0.7})
    front, _, _ = front_left_right(ranges, a0, inc, min_valid=0.05)
    assert front == 0.7


def test_sector_with_no_usable_reading_is_nan():
    ranges, a0, inc = scan({}, default=0.0)
    assert math.isnan(sector_min(ranges, a0, inc, 0.0, math.radians(15), 0.05))
