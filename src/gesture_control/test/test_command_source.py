import sys
import threading

import pytest

from gesture_control.command_source import GesturePipeline, LatestWord
from gesture_control.keyboard_source import KeyboardCommand, KeyFilter
from gesture_control.smoother import WordSmoother

from hands import FIST, at_angle, make_hand


def test_latest_word_starts_none():
    assert LatestWord().get(0.0) == "none"


def test_latest_word_fresh_then_stale():
    lw = LatestWord(stale_s=0.3)
    lw.set("forward", 10.0)
    assert lw.get(10.0) == "forward"
    assert lw.get(10.29) == "forward"
    assert lw.get(10.31) == "none"
    lw.set("left", 10.4)
    assert lw.get(10.5) == "left"


@pytest.mark.parametrize("stale", [0.0, 0.5, 1.0])
def test_stale_must_be_below_robot_timeout(stale):
    with pytest.raises(ValueError):
        LatestWord(stale_s=stale)


def test_latest_word_rejects_unknown():
    with pytest.raises(ValueError):
        LatestWord().set("go", 0.0)


def test_latest_word_threads():
    lw = LatestWord()

    def writer():
        for i in range(2000):
            lw.set("forward" if i % 2 else "left", 1.0)

    th = threading.Thread(target=writer)
    th.start()
    for _ in range(2000):
        assert lw.get(1.0) in ("forward", "left", "none")
    th.join()


def test_pipeline_end_to_end():
    pl = GesturePipeline(smoother=WordSmoother(confirm_frames=3, dropout_hold_s=0.3))
    t = 0.0
    words = []
    for _ in range(3):
        w, r = pl.step(make_hand(at_angle(90, 0.3)), t)
        words.append(w)
        t += 0.033
    assert words[-1] == "right"
    assert r.word == "right"
    for _ in range(3):
        w, _ = pl.step(make_hand(at_angle(90, 0.3), FIST), t)
        t += 0.033
    assert w == "stop"
    w, r = pl.step(None, t)
    assert (w, r) == ("stop", None)
    w, _ = pl.step(None, t + 0.4)
    assert w == "none"


def test_held_word_stamped_with_last_hand():
    # Dropout hold and stale_s overlap: a held word goes stale stale_s after
    # the hand was last seen, not stale_s after the end of the hold.
    pl = GesturePipeline(smoother=WordSmoother(confirm_frames=1, dropout_hold_s=0.3))
    lw = LatestWord(stale_s=0.3)
    w, _ = pl.step(make_hand(at_angle(0, 0.3)), 1.0)
    lw.set(w, pl.last_stamp)
    assert (w, pl.last_stamp) == ("forward", 1.0)
    w, _ = pl.step(None, 1.25)  # hand lost, word held
    lw.set(w, pl.last_stamp)
    assert (w, pl.last_stamp) == ("forward", 1.0)
    # camera stalls now: the held word must be gone by last hand + stale_s
    assert lw.get(1.29) == "forward"
    assert lw.get(1.31) == "none"
    w, _ = pl.step(None, 1.35)  # hold over: fresh none, stamped now
    assert (w, pl.last_stamp) == ("none", 1.35)


def test_worst_case_drive_word_after_hand_lost_below_robot_timeout():
    pl = GesturePipeline(smoother=WordSmoother(confirm_frames=1, dropout_hold_s=0.49))
    lw = LatestWord(stale_s=0.49)
    pl.step(make_hand(at_angle(0, 0.3)), 0.0)
    t = 0.0
    while t < 0.48:
        t += 0.033
        w, _ = pl.step(None, t)
        lw.set(w, pl.last_stamp)
    assert lw.get(0.5) == "none"


def test_pipeline_reset_requires_reconfirm():
    pl = GesturePipeline(smoother=WordSmoother(confirm_frames=3, back_confirm_frames=6))
    t = 0.0
    for _ in range(6):
        w, _ = pl.step(make_hand(at_angle(180, 0.3)), t)
        t += 0.033
    assert w == "back"
    pl.reset()  # camera gap
    assert pl.classifier.prev is None
    w, _ = pl.step(make_hand(at_angle(180, 0.3)), t + 2.0)
    assert w == "none"  # back must be confirmed again, not restored at once


def test_keyboard_hold_and_release():
    kb = KeyboardCommand(hold_s=0.6)
    assert kb.word(0.0) == "none"
    assert kb.press("w", 1.0) == "forward"
    assert kb.word(1.5) == "forward"
    assert kb.word(1.7) == "none"
    kb.press(" ", 2.0)
    assert kb.word(2.0) == "stop"
    kb.press("x", 2.1)
    assert kb.word(2.1) == "none"
    assert kb.press("q", 3.0) is None
    # Exact lowercase only: uppercase letters end arrow / F-key sequences.
    for key in "WASDX":
        assert kb.press(key, 3.0) is None


def _filtered(chars):
    f = KeyFilter()
    return "".join(c for c in (f.feed(ch) for ch in chars) if c)


def test_key_filter_drops_arrow_and_function_keys():
    # Up, down, right, left arrows; F1 (SS3); Ctrl+Right (CSI with params).
    seq = "\x1b[A\x1b[B\x1b[C\x1b[D\x1bOP\x1b[1;5C"
    assert _filtered(seq) == ""
    assert _filtered("w\x1b[Ds") == "ws"


def test_key_filter_drops_windows_scan_codes():
    # msvcrt: arrows arrive as \xe0 then H/P/K/M; F-keys as \x00 then a code.
    assert _filtered("\xe0H\xe0K\x00;d") == "d"


def test_arrow_keys_never_drive():
    kb, f = KeyboardCommand(hold_s=0), KeyFilter()
    for ch in "\x1b[A\x1b[D\x1b[B\x1b[C":
        c = f.feed(ch)
        if c:
            kb.press(c, 0.0)
    assert kb.word(0.0) == "none"


def test_keyboard_force_none_overrides_latch():
    kb = KeyboardCommand(hold_s=0)
    kb.press("w", 0.0)
    kb.force_none(1.0)
    assert kb.word(100.0) == "none"


def test_keyboard_latched():
    kb = KeyboardCommand(hold_s=0)
    kb.press("a", 0.0)
    assert kb.word(100.0) == "left"


def test_keyboard_default_outlasts_key_repeat_delay():
    # Terminal key repeat starts after about 0.5 to 0.66 s; a shorter hold
    # would publish a "none" gap and reset the state machine's 1 s back hold.
    assert KeyboardCommand().hold_s > 0.66


def test_pure_modules_do_not_pull_heavy_imports():
    # These import cv2 / MediaPipe only inside functions. gesture_node needs rclpy.
    import gesture_control.camera_loop  # noqa: F401
    import gesture_control.hand_tracker  # noqa: F401
    import gesture_control.webcam_demo  # noqa: F401
    heavy = ("rclpy", "mediapipe", "cv2", "numpy")
    for mod in heavy:
        assert mod not in sys.modules, "%s imported by a pure module" % mod
