import pytest

from obstacle_avoidance.gyro import GyroYaw


def test_integrates_the_rate():
    g = GyroYaw()
    for i in range(11):
        g.update(i * 0.02, 1.0, i * 0.02)  # 1 rad/s for 0.2 s
    assert g.yaw(0.2) == pytest.approx(0.2)


def test_none_before_the_first_reading():
    assert GyroYaw().yaw(0.0) is None


def test_none_while_silent_then_back():
    g = GyroYaw(timeout=0.2)
    g.update(0.0, 1.0, 0.0)
    g.update(0.1, 1.0, 0.1)
    assert g.yaw(0.3) == pytest.approx(0.1)
    assert g.yaw(0.31) is None
    g.update(0.4, 1.0, 0.4)  # 0.3 s gap: integrated, under max_gap
    assert g.yaw(0.4) == pytest.approx(0.4)


def test_skips_a_long_gap():
    g = GyroYaw(max_gap=0.5)
    g.update(0.0, 1.0, 0.0)
    g.update(2.0, 1.0, 2.0)
    assert g.yaw(2.0) == 0.0
