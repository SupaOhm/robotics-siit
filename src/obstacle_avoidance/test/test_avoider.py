import math

import pytest

from obstacle_avoidance.avoider import AckermannAvoider, Avoider, EventType, make_avoider


def make(**kw):
    kw.setdefault("clear_distance", 0.40)
    kw.setdefault("turn_speed", 1.0)
    kw.setdefault("min_turn", 0.5)
    kw.setdefault("max_turn", 3.0)
    kw.setdefault("clear_time", 0.2)
    return Avoider(**kw)


def run(a, front, t0=0.0, until=10.0, dt=0.05, yaw=lambda t: None):
    """Tick until the turn ends; ``front`` and ``yaw`` map time -> distance
    and IMU yaw (None = no IMU)."""
    t = t0
    while t <= until:
        events = a.tick(t, front(t), yaw=yaw(t))
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


def test_measured_yaw_counts_the_turn():
    a = make()
    a.start(0.0, left=0.5, right=2.0, yaw=0.0)  # turns right
    a.tick(1.0, 0.2, yaw=-0.3)  # commands say 1 rad, the IMU says 0.3
    assert a.turned_angle == pytest.approx(0.3)


def test_slipping_wheels_turn_longer():
    a = make(min_turn=1.0)
    a.start(0.0, yaw=0.0)
    t, result = run(a, lambda t: 1.0, yaw=lambda t: 0.5 * t)  # half the commanded rate
    assert result == EventType.DONE
    assert t >= 2.0


def test_gives_up_on_time_when_the_robot_does_not_turn():
    a = make(max_turn=2.0)
    a.start(0.0, yaw=0.0)
    t, result = run(a, lambda t: 1.0, yaw=lambda t: 0.0)
    assert result == EventType.FAILED
    assert 2.0 <= t < 2.1


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


# --- AckermannAvoider ---------------------------------------------------------

def car(**kw):
    kw.setdefault("speed", 0.15)
    kw.setdefault("wheelbase", 0.16)
    kw.setdefault("max_steer", math.radians(30))
    return AckermannAvoider(**kw)


def drive(a, front, rear=lambda turned: math.inf, use_yaw=True, dt=0.05, until=20.0,
          left=math.inf, right=math.inf):
    """Start a turn and step a car that follows the commands. ``front`` and
    ``rear`` map the turned angle (rad, toward the turn) to a distance."""
    t, yaw = 0.0, 0.0
    a.start(t, left, right, yaw if use_yaw else None)
    commands = []
    while t < until:
        linear, angular = a.command
        commands.append((linear, angular, a.phase))
        t += dt
        yaw += angular * dt
        turned = a.direction * yaw
        events = a.tick(t, front(turned), rear(turned), yaw if use_yaw else None)
        if events:
            return events[-1].type, commands, t
    return None, commands, t


def wall_until(deg):
    return lambda turned: 1.0 if turned >= math.radians(deg) else 0.27


def test_ackermann_never_turns_in_place():
    _, commands, _ = drive(car(), wall_until(70))
    assert commands
    assert all(linear != 0 for linear, angular, _ in commands if angular != 0)


def test_ackermann_backs_up_then_arcs_the_same_way():
    a = car()
    result, commands, _ = drive(a, wall_until(70), right=0.3, left=2.0)
    phases = [p for _, _, p in commands]
    assert phases[0] == AckermannAvoider.BACKING and commands[0][0] < 0
    first_arc = phases.index(AckermannAvoider.ARC)
    assert commands[first_arc][0] > 0
    assert commands[0][1] > 0 and commands[first_arc][1] > 0  # both swing left
    assert result == EventType.DONE


def test_backing_stops_after_back_turn():
    a = car(back_turn=math.radians(30))
    _, commands, _ = drive(a, wall_until(70))
    backing = sum(1 for _, _, p in commands[:200] if p == AckermannAvoider.BACKING)
    # 30 deg at the full-lock yaw rate, in 0.05 s steps
    assert backing == pytest.approx(math.radians(30) / a.yaw_rate / 0.05, abs=1)


def test_rear_obstacle_cuts_backing_short():
    a = car()
    a.start(0.0)
    a.tick(0.05, 0.27, rear=0.1)
    assert a.phase == AckermannAvoider.ARC


def test_max_reverse_limits_backing_when_the_car_does_not_turn():
    a = car(max_reverse=0.25)
    a.start(0.0, yaw=0.0)
    t = 0.0
    while a.phase == AckermannAvoider.BACKING:
        t += 0.05
        a.tick(t, 0.27, yaw=0.0)  # steering jammed: heading never changes
    assert t == pytest.approx(0.25 / a.speed, abs=0.06)


def test_blocked_arc_backs_up_again_then_fails():
    a = car(max_cycles=3)
    result, commands, _ = drive(a, lambda turned: 0.15, until=60)
    assert result == EventType.FAILED
    assert a.cycles == 3


def test_ackermann_dead_reckoning_without_yaw():
    a = car()
    result, _, _ = drive(a, wall_until(70), use_yaw=False)
    assert result == EventType.DONE


def test_measured_yaw_beats_dead_reckoning():
    a = car(min_turn=math.radians(60))
    a.start(0.0, yaw=0.0)
    a.tick(1.0, 1.0, yaw=0.1)  # commands say ~0.54 rad, the IMU says 0.1
    assert a.turned_angle == pytest.approx(0.1)


def test_make_avoider():
    yaml = {"drive_type": "ackermann", "clear_distance": 0.4, "min_turn_deg": 30,
            "max_turn_deg": 270, "clear_time": 0.3, "default_direction": 1,
            "turn_speed": 1.0, "avoid_speed": 0.15, "wheelbase": 0.16,
            "max_steer_deg": 30, "back_turn_deg": 30, "max_reverse": 0.25,
            "rear_clear": 0.2, "arc_min_front": 0.2, "max_cycles": 3}
    assert isinstance(make_avoider(yaml.__getitem__), AckermannAvoider)
    yaml["drive_type"] = "diff"
    assert isinstance(make_avoider(yaml.__getitem__), Avoider)
    yaml["drive_type"] = "tank"
    with pytest.raises(ValueError):
        make_avoider(yaml.__getitem__)
