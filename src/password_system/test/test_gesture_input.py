from password_system.gesture_input import GestureDebouncer

FPS = 15.0


def run(debouncer, readings, start=0.0):
    """readings: list of (value, seconds). Returns accepted tokens."""
    t = start
    out = []
    for value, duration in readings:
        for _ in range(int(duration * FPS)):
            tok = debouncer.update(value, t)
            if tok is not None:
                out.append(tok)
            t += 1.0 / FPS
    return out


def test_hold_registers_once():
    d = GestureDebouncer(hold_time=0.8)
    assert run(d, [(3, 3.0)]) == ["3"]


def test_short_flash_ignored():
    d = GestureDebouncer(hold_time=0.8)
    assert run(d, [(2, 0.5), (None, 1.0)]) == []


def test_different_digits_without_release():
    d = GestureDebouncer()
    assert run(d, [(1, 1.0), (3, 1.0), (5, 1.0)]) == ["1", "3", "5"]


def test_same_digit_twice_needs_release():
    d = GestureDebouncer()
    assert run(d, [(2, 1.0), (2, 1.0)]) == ["2"]
    d.reset()
    assert run(d, [(2, 1.0), (0, 0.6), (2, 1.0)]) == ["2", "2"]
    d.reset()
    assert run(d, [(2, 1.0), (None, 0.6), (2, 1.0)]) == ["2", "2"]


def test_brief_dropout_does_not_break_hold():
    d = GestureDebouncer(hold_time=0.8, release_time=0.4)
    assert run(d, [(4, 0.5), (None, 0.2), (4, 0.5)]) == ["4"]


def test_brief_dropout_is_not_a_release():
    d = GestureDebouncer(hold_time=0.8, release_time=0.4)
    assert run(d, [(4, 1.0), (None, 0.2), (4, 1.0)]) == ["4"]


def test_fist_and_invalid_are_separators():
    d = GestureDebouncer()
    assert run(d, [(0, 2.0), (7, 2.0)]) == []


def test_progress():
    d = GestureDebouncer(hold_time=1.0)
    d.update(3, 0.0)
    cand, frac = d.progress(0.5)
    assert cand == "3" and abs(frac - 0.5) < 1e-9
