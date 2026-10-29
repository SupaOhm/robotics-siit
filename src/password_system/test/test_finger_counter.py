import math

import pytest

from password_system.finger_counter import count_fingers

# Synthetic right hand, palm to camera, fingers up (pixel coords, y down).
# Each finger: (mcp, pip, dip, tip) extended and curled.
WRIST = (100, 200)
THUMB = {
    True: [(80, 190), (65, 175), (50, 160), (38, 148)],
    False: [(80, 190), (65, 175), (80, 160), (100, 155)],
}
FINGERS = {
    "index": {True: [(80, 140), (78, 115), (77, 100), (76, 85)],
              False: [(80, 140), (78, 115), (82, 130), (84, 140)]},
    "middle": {True: [(95, 138), (95, 110), (95, 94), (95, 78)],
               False: [(95, 138), (95, 110), (96, 128), (95, 140)]},
    "ring": {True: [(110, 140), (112, 115), (113, 100), (114, 85)],
             False: [(110, 140), (112, 115), (113, 132), (112, 142)]},
    "pinky": {True: [(125, 145), (130, 125), (132, 115), (134, 105)],
              False: [(125, 145), (130, 125), (130, 138), (128, 148)]},
}


def make_hand(thumb=False, index=False, middle=False, ring=False, pinky=False):
    pts = [WRIST] + THUMB[thumb]
    for name, up in (("index", index), ("middle", middle), ("ring", ring),
                     ("pinky", pinky)):
        pts += FINGERS[name][up]
    assert len(pts) == 21
    return pts


def rotate(points, degrees):
    a = math.radians(degrees)
    c, s = math.cos(a), math.sin(a)
    return [(x * c - y * s, x * s + y * c) for x, y in points]


@pytest.mark.parametrize("kwargs,expected", [
    ({}, 0),
    ({"index": True}, 1),
    ({"index": True, "middle": True}, 2),
    ({"index": True, "middle": True, "ring": True}, 3),
    ({"index": True, "middle": True, "ring": True, "pinky": True}, 4),
    ({"thumb": True, "index": True, "middle": True, "ring": True, "pinky": True}, 5),
    ({"thumb": True}, 1),
])
def test_counts(kwargs, expected):
    assert count_fingers(make_hand(**kwargs)) == expected


@pytest.mark.parametrize("deg", [45, 90, 180, -60])
def test_rotation_invariant(deg):
    hand = make_hand(index=True, middle=True, ring=True)
    assert count_fingers(rotate(hand, deg)) == 3


def test_wrong_landmark_count():
    with pytest.raises(ValueError):
        count_fingers([(0, 0)] * 20)
