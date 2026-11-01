"""Webcam -> MediaPipe -> classifier -> smoother, shared by gesture_node and
webcam_demo. cv2 and MediaPipe are imported inside the functions.

Each processed frame calls ``on_word(word, stamp)``. When the camera or the
tracker fails, no call is made, so the caller's ``LatestWord`` goes stale and
the node publishes ``none``, and the pipeline is reset, so the first word
after the gap must be confirmed again. The loop keeps retrying the camera.
"""

import threading
import time
from typing import Callable, Optional

from .command_source import GesturePipeline

# MediaPipe hand skeleton, so drawing works with either MediaPipe backend.
HAND_CONNECTIONS = (
    (0, 1), (1, 2), (2, 3), (3, 4),
    (0, 5), (5, 6), (6, 7), (7, 8),
    (5, 9), (9, 10), (10, 11), (11, 12),
    (9, 13), (13, 14), (14, 15), (15, 16),
    (13, 17), (17, 18), (18, 19), (19, 20), (0, 17),
)

COLORS = {"stop": (0, 0, 255), "none": (200, 200, 200)}  # BGR; directions green


def draw_overlay(frame, landmarks, result, word: str, deadzone_radius: float) -> None:
    import cv2

    h, w = frame.shape[:2]
    center = (w // 2, h // 2)
    cv2.circle(frame, center, int(deadzone_radius * h), (255, 255, 255), 1)
    cv2.circle(frame, center, 4, (255, 255, 255), -1)
    color = COLORS.get(word, (0, 255, 0))
    if landmarks is not None:
        pts = [(int(x * w), int(y * h)) for x, y in landmarks]
        for a, b in HAND_CONNECTIONS:
            cv2.line(frame, pts[a], pts[b], (255, 200, 0), 2)
        for p in pts:
            cv2.circle(frame, p, 3, (0, 200, 255), -1)
    if result is not None:
        hc = (int(result.center[0] * w), int(result.center[1] * h))
        cv2.line(frame, center, hc, color, 2)
        cv2.putText(frame, "fingers %d  angle %+4.0f  dist %.2f"
                    % (result.extended, result.angle, result.distance),
                    (10, h - 15), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
    cv2.putText(frame, word, (10, 40), cv2.FONT_HERSHEY_SIMPLEX, 1.2, color, 3)


def run_camera(pipeline: GesturePipeline, on_word: Callable[[str, float], None],
               stop: threading.Event, camera_index: int = 0, model_path: str = "",
               show_window: bool = False, esc_quits: bool = False,
               log: Callable[[str], None] = print,
               clock: Callable[[], float] = time.monotonic,
               window_name: str = "gesture_control") -> None:
    """Run until ``stop`` is set (or ESC / q in the window if ``esc_quits``)."""
    import cv2

    from .hand_tracker import HandTracker

    tracker = HandTracker(model_path, log=log)
    log("hand tracker backend: %s" % tracker.backend)
    cap: Optional[object] = None
    failing = False
    try:
        while not stop.is_set():
            if cap is None:
                cap = cv2.VideoCapture(camera_index)
                if not cap.isOpened():
                    if not failing:
                        log("cannot open camera %d, retrying" % camera_index)
                        failing = True
                    cap.release()
                    cap = None
                    pipeline.reset()
                    stop.wait(1.0)
                    continue
            ok, frame = cap.read()
            if not ok or frame is None:
                if not failing:
                    log("camera read failed, reopening")
                    failing = True
                cap.release()
                cap = None
                pipeline.reset()
                stop.wait(0.5)
                continue

            frame = cv2.flip(frame, 1)  # mirror: operator's right is screen right
            h, w = frame.shape[:2]
            now = clock()
            try:
                landmarks = tracker.process(frame, now)
            except Exception as e:  # keep going; the caller's word goes stale
                if not failing:
                    log("hand tracker error: %r" % e)
                    failing = True
                pipeline.reset()
                continue
            if failing:
                log("camera and tracker running")
                failing = False
            word, result = pipeline.step(landmarks, now, aspect=w / float(h))
            on_word(word, pipeline.last_stamp)

            if show_window:
                draw_overlay(frame, landmarks, result, word,
                             pipeline.classifier.params.deadzone_radius)
                cv2.imshow(window_name, frame)
                key = cv2.waitKey(1) & 0xFF
                if esc_quits and key in (27, ord("q")):
                    stop.set()
    finally:
        if cap is not None:
            cap.release()
        tracker.close()
        if show_window:
            try:
                cv2.destroyWindow(window_name)
            except Exception:
                pass
