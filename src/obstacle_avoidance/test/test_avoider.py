import math

import pytest

from obstacle_avoidance.avoider import Avoider, EventType


def make(**kw):
    kw.setdefault("clear_distance", 0.40)
    kw.setdefault("turn_speed", 1.0)
    kw.setdefault("min_turn", 0.5)
    kw.setdefault("max_turn", 3.0)
    kw.setdefault("clear_time", 0.2)
    return Avoider(**kw)


def run(a, front, t0=0.0, until=10.0, dt=0.05):
    """Tick until the turn ends; ``front`` maps time -> distance."""
    t = t0
    while t <= until:
        events = a.tick(t, front(t))
        if events:
            return t, events[-1].type
        t += dt
    return t, None


def test_turns_toward_more_room():
    a = make()
    assert a.start(0.0, left=0.5, right=2.0)[0].direction == -1
    assert a.angular_velocity == -1.0
    a = make()
    assert a.start(0.0, left=2.0, right=0.5)[0].direction == 1


def test_ultrasonic_uses_default_direction():
    a = make(default_direction=-1)
    assert a.start(0.0)[0].direction == -1


def test_done_after_front_clears():
    a = make()
    a.start(0.0)
    t, result = run(a, lambda t: 0.2 if t < 1.0 else 1.0)
    assert result == EventType.DONE
    assert 1.2 <= t < 1.3
    assert not a.active
    assert a.angular_velocity == 0.0


def test_keeps_turning_for_min_turn_even_if_clear():
    a = make(min_turn=1.0)
    a.start(0.0)
    t, result = run(a, lambda t: 1.0)
    assert result == EventType.DONE
    assert t >= 1.0


def test_clear_must_last_clear_time():
    a = make()
    a.start(0.0)
    blips = lambda t: 1.0 if 0.6 <= t < 0.7 or t >= 2.0 else 0.2
    t, result = run(a, blips)
    assert result == EventType.DONE
    assert t >= 2.2


def test_fails_when_boxed_in():
    a = make(max_turn=2.0)
    a.start(0.0)
    t, result = run(a, lambda t: 0.2)
    assert result == EventType.FAILED
    assert t >= 2.0


def test_cancel_and_fail_only_when_active():
    a = make()
    assert a.cancel() == []
    assert a.fail() == []
    a.start(0.0)
    assert a.cancel()[0].type == EventType.CANCELLED
    a.start(0.0)
    assert a.fail()[0].type == EventType.FAILED
    assert a.tick(1.0, 1.0) == []


def test_bad_config():
    with pytest.raises(ValueError):
        Avoider(turn_speed=0)
    with pytest.raises(ValueError):
        Avoider(min_turn=math.pi, max_turn=1.0)
    with pytest.raises(ValueError):
        Avoider(default_direction=0)
