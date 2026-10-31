import math

import pytest

from obstacle_avoidance.range_filter import RangeFilter


def test_empty_until_first_valid_reading():
    f = RangeFilter()
    assert f.value is None
    assert f.update(math.nan) is None
    assert f.update(0.0) is None
    assert f.update(1.0) == 1.0


def test_median_ignores_one_spike():
    f = RangeFilter(window=5)
    for r in (1.0, 1.0, 0.05, 1.0, 1.0):
        f.update(r)
    assert f.value == 1.0


def test_inf_and_far_count_as_max_range():
    f = RangeFilter(window=1, max_range=4.0)
    assert f.update(math.inf) == 4.0
    assert f.update(9.0) == 4.0


def test_window_forgets_old_readings():
    f = RangeFilter(window=3)
    for r in (2.0, 2.0, 2.0, 0.5, 0.5):
        f.update(r)
    assert f.value == 0.5


def test_reset():
    f = RangeFilter()
    f.update(1.0)
    f.reset()
    assert f.value is None


def test_bad_config():
    with pytest.raises(ValueError):
        RangeFilter(window=0)
    with pytest.raises(ValueError):
        RangeFilter(min_range=2.0, max_range=1.0)


def test_valid():
    f = RangeFilter(min_range=0.02)
    assert f.valid(0.5)
    assert f.valid(math.inf)
    assert not f.valid(0.0)
    assert not f.valid(math.nan)
