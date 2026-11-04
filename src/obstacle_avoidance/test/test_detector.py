import pytest

from obstacle_avoidance.detector import ObstacleDetector


def test_blocks_at_stop_distance():
    d = ObstacleDetector(stop_distance=0.30, clear_distance=0.40)
    assert d.update(1.0) is False
    assert d.update(0.30) is True


def test_hysteresis_keeps_blocked_between_thresholds():
    d = ObstacleDetector(stop_distance=0.30, clear_distance=0.40)
    d.update(0.25)
    assert d.update(0.35) is True
    assert d.update(0.39) is True
    assert d.update(0.40) is False


def test_not_blocked_between_thresholds_when_approaching():
    d = ObstacleDetector(stop_distance=0.30, clear_distance=0.40)
    assert d.update(0.35) is False


def test_bad_config():
    with pytest.raises(ValueError):
        ObstacleDetector(stop_distance=0.5, clear_distance=0.4)
