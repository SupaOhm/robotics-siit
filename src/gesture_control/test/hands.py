"""Synthetic MediaPipe-style hands for the tests (21 normalized (x, y))."""

import math

# Finger base x offsets from the wrist (index..pinky), hand pointing up.
_BASES = (-0.03, -0.01, 0.01, 0.03)


def make_hand(center=(0.5, 0.5), fingers=(True, True, True, True), thumb_out=True,
              rotate_deg=0.0, scale=1.0):
    """A hand whose landmark bbox centre is ``center``.

    ``fingers``: extended flags for index, middle, ring, pinky. A curled
    finger's tip folds back towards the wrist. ``rotate_deg`` turns the whole
    hand about the wrist (positive = clockwise on screen).
    """
    pts = [(0.0, 0.0)] * 21
    pts[0] = (0.0, 0.0)                                   # wrist
    # Thumb 1..4: out to the side, or tucked across the palm.
    if thumb_out:
        thumb = [(-0.03, -0.02), (-0.06, -0.04), (-0.08, -0.06), (-0.10, -0.08)]
    else:
        thumb = [(-0.02, -0.02), (-0.03, -0.04), (-0.02, -0.06), (-0.01, -0.07)]
    for i, p in enumerate(thumb):
        pts[1 + i] = p
    for f, (bx, ext) in enumerate(zip(_BASES, fingers)):
        mcp, pip, dip, tip = 5 + 4 * f, 6 + 4 * f, 7 + 4 * f, 8 + 4 * f
        pts[mcp] = (bx, -0.08)
        pts[pip] = (bx, -0.11)
        if ext:
            pts[dip] = (bx, -0.13)
            pts[tip] = (bx, -0.15)
        else:                                             # folded into the palm
            pts[dip] = (bx, -0.08)
            pts[tip] = (bx, -0.06)

    r = math.radians(rotate_deg)
    c, s = math.cos(r), math.sin(r)
    # Image y points down, so clockwise on screen is this rotation.
    pts = [((x * c - y * s) * scale, (x * s + y * c) * scale) for x, y in pts]

    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    mx, my = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
    return [(x - mx + center[0], y - my + center[1]) for x, y in pts]


def at_angle(angle_deg, dist, frame_center=(0.5, 0.5)):
    """Point at ``dist`` from the centre, angle 0 = above, +90 = right."""
    a = math.radians(angle_deg)
    return (frame_center[0] + dist * math.sin(a), frame_center[1] - dist * math.cos(a))


OPEN = (True, True, True, True)
FIST = (False, False, False, False)
