import pytest

from gesture_control.smoother import WordSmoother

DT = 1 / 30.0  # webcam frame period


def feed(s, words, t0=0.0):
    t, out = t0, []
    for w in words:
        out.append(s.update(w, t))
        t += DT
    return out, t


def test_starts_none():
    assert WordSmoother().current == "none"


def test_new_word_needs_confirm_frames():
    s = WordSmoother(confirm_frames=3)
    out, _ = feed(s, ["forward"] * 3)
    assert out == ["none", "none", "forward"]


def test_flicker_does_not_switch():
    s = WordSmoother(confirm_frames=3)
    out, _ = feed(s, ["forward", "forward", "left", "forward", "forward", "forward"])
    assert out[-1] == "forward"
    assert "left" not in out


def test_back_needs_more_frames():
    s = WordSmoother(confirm_frames=3, back_confirm_frames=6)
    out, _ = feed(s, ["back"] * 6)
    assert out[:5] == ["none"] * 5
    assert out[5] == "back"


def test_back_interrupted_restarts_count():
    s = WordSmoother(confirm_frames=3, back_confirm_frames=6)
    out, _ = feed(s, ["back"] * 5 + ["right"] + ["back"] * 5)
    assert "back" not in out


def test_stop_takes_over_on_first_frame():
    s = WordSmoother(confirm_frames=3)
    feed(s, ["forward"] * 3)
    out, _ = feed(s, ["stop"], t0=1.0)
    assert out == ["stop"]


@pytest.mark.parametrize("pattern", [
    ["stop", "stop", None],      # fist lost every third frame (PR #14 review)
    ["stop", "stop", "right"],   # fist misread every third frame
    ["stop", None, None],
    ["stop", "forward", "forward"],
])
def test_flickering_fist_stops_and_stays_stopped(pattern):
    """After forward, a fist that MediaPipe keeps losing must still stop the
    robot, and the published word must stay stop, fed through LatestWord as
    the node does, for 3 s at 30 fps."""
    from gesture_control.command_source import LatestWord
    s, latest = WordSmoother(confirm_frames=3), LatestWord()
    out, t = feed(s, ["forward"] * 3)
    assert out[-1] == "forward"
    published = []
    for i in range(90):
        word = s.update(pattern[i % len(pattern)], t)
        latest.set(word, t)
        published.append(latest.get(t))
        t += DT
    assert published[0] == "stop"
    assert set(published) == {"stop"}


def test_moving_again_after_stop_needs_confirm_frames():
    s = WordSmoother(confirm_frames=3)
    feed(s, ["stop"])
    out, _ = feed(s, ["forward"] * 3, t0=1.0)
    assert out == ["stop", "stop", "forward"]


def test_dropout_holds_then_none():
    s = WordSmoother(dropout_hold_s=0.3)
    _, t = feed(s, ["forward"] * 3)
    last_hand = t - DT
    assert s.update(None, last_hand + 0.1) == "forward"
    assert s.update(None, last_hand + 0.29) == "forward"
    assert s.update(None, last_hand + 0.3) == "none"
    assert s.update(None, last_hand + 1.0) == "none"


def test_dropout_recovers_within_hold():
    s = WordSmoother(dropout_hold_s=0.3)
    _, t = feed(s, ["forward"] * 3)
    assert s.update(None, t) == "forward"
    assert s.update("forward", t + DT) == "forward"


def test_no_hand_from_start_is_none():
    s = WordSmoother()
    assert s.update(None, 0.0) == "none"


@pytest.mark.parametrize("hold", [0.5, 0.6, -0.1])
def test_hold_must_stay_below_robot_timeout(hold):
    with pytest.raises(ValueError):
        WordSmoother(dropout_hold_s=hold)


def test_back_confirm_not_below_confirm():
    with pytest.raises(ValueError):
        WordSmoother(confirm_frames=4, back_confirm_frames=2)


def test_unknown_word_rejected():
    with pytest.raises(ValueError):
        WordSmoother().update("jump", 0.0)
