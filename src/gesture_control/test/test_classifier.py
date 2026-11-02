import pytest

from gesture_control.classifier import (ClassifierParams, GestureClassifier, classify,
                                        count_extended, hand_center)

from hands import FIST, OPEN, at_angle, make_hand


def word(center, fingers=OPEN, prev=None, **kw):
    return classify(make_hand(center, fingers, **kw), prev=prev).word


def test_make_hand_puts_bbox_centre_where_asked():
    c = hand_center(make_hand((0.3, 0.7)))
    assert c == pytest.approx((0.3, 0.7))


def test_open_hand_counts_four():
    assert count_extended(make_hand()) == 4


@pytest.mark.parametrize("rot", [0, 45, 90, -90, 180])
def test_finger_count_ignores_rotation(rot):
    assert count_extended(make_hand(rotate_deg=rot)) == 4
    assert count_extended(make_hand(fingers=FIST, rotate_deg=rot)) == 0


@pytest.mark.parametrize("center", [(0.5, 0.5), (0.5, 0.2), (0.85, 0.5), (0.5, 0.85)])
def test_fist_is_stop_anywhere(center):
    assert word(center, FIST) == "stop"


def test_fist_with_thumb_out_is_still_stop():
    assert word(at_angle(0, 0.3), FIST, thumb_out=True) == "stop"
    assert word(at_angle(0, 0.3), FIST, thumb_out=False) == "stop"


def test_one_finger_is_stop_two_is_open():
    assert word(at_angle(0, 0.3), (True, False, False, False)) == "stop"
    assert word(at_angle(0, 0.3), (True, True, False, False)) == "forward"


@pytest.mark.parametrize("angle,expected", [
    (0, "forward"), (25, "forward"), (-25, "forward"),
    (90, "right"), (60, "right"), (120, "right"),
    (-90, "left"), (-60, "left"), (-120, "left"),
    (180, "back"), (160, "back"), (-160, "back"),
])
def test_open_hand_sectors(angle, expected):
    assert word(at_angle(angle, 0.3)) == expected


def test_centre_is_none_not_stop():
    assert word((0.5, 0.5)) == "none"
    assert word(at_angle(45, 0.05)) == "none"


def test_angle_convention():
    r = classify(make_hand(at_angle(90, 0.3)))
    assert r.angle == pytest.approx(90, abs=0.5)
    assert r.distance == pytest.approx(0.3, abs=1e-6)


def test_sector_hysteresis_keeps_previous_word_near_border():
    # 34 deg: plain sector is right, but forward sticks within 30 + 8.
    assert word(at_angle(34, 0.3)) == "right"
    assert word(at_angle(34, 0.3), prev="forward") == "forward"
    assert word(at_angle(40, 0.3), prev="forward") == "right"
    # And the other way: 26 deg stays right if it was right.
    assert word(at_angle(26, 0.3)) == "forward"
    assert word(at_angle(26, 0.3), prev="right") == "right"
    # Back border.
    assert word(at_angle(-145, 0.3), prev="back") == "back"
    assert word(at_angle(-145, 0.3), prev="left") == "left"
    assert word(at_angle(-145, 0.3)) == "left"


def test_deadzone_hysteresis():
    p = ClassifierParams()
    inside_band = p.deadzone_radius + p.deadzone_hysteresis / 2   # 0.13
    assert word(at_angle(0, inside_band), prev="none") == "none"
    assert word(at_angle(0, inside_band), prev="forward") == "forward"
    just_in = p.deadzone_radius - p.deadzone_hysteresis / 2       # 0.11
    assert word(at_angle(0, just_in), prev="forward") == "forward"
    assert word(at_angle(0, just_in), prev="none") == "none"
    assert word(at_angle(0, 0.05), prev="forward") == "none"


def test_aspect_scales_x():
    # 0.1 to the right on a 16:9 frame is 0.178 frame heights: outside the deadzone.
    lm = make_hand((0.6, 0.5))
    assert classify(lm, aspect=1.0).word == "none"
    assert classify(lm, aspect=16 / 9).word == "right"


def test_custom_frame_center():
    lm = make_hand((0.5, 0.2))
    assert classify(lm, frame_center=(0.5, 0.2)).word == "none"


def test_wrong_landmark_count_raises():
    with pytest.raises(ValueError):
        classify([(0.5, 0.5)] * 20)


def test_bad_params_rejected():
    with pytest.raises(ValueError):
        GestureClassifier(ClassifierParams(forward_half_angle=160, back_min_angle=150))


def test_stateful_classifier_uses_and_resets_prev():
    c = GestureClassifier()
    assert c(make_hand(at_angle(0, 0.3))).word == "forward"
    assert c(make_hand(at_angle(34, 0.3))).word == "forward"   # hysteresis
    assert c(None) is None
    assert c(make_hand(at_angle(34, 0.3))).word == "right"     # prev cleared
