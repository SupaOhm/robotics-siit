"""MediaPipe hand tracking. MediaPipe is imported inside the class, so the
rest of the package (and the tests) work without it.

Prefers the Tasks API (``HandLandmarker``, VIDEO mode, needs the
``hand_landmarker.task`` model file). Falls back to the legacy
``mp.solutions.hands`` when the Tasks API is missing, or the model file is
missing or unreadable, and the installed MediaPipe still has ``solutions``.
"""

import os
from typing import List, Optional, Tuple

MODEL_URL = ("https://storage.googleapis.com/mediapipe-models/hand_landmarker/"
             "hand_landmarker/float16/latest/hand_landmarker.task")


class HandTracker:
    def __init__(self, model_path: str = "", min_detection_confidence: float = 0.7,
                 min_tracking_confidence: float = 0.7, min_presence_confidence: float = 0.5,
                 log=print):
        import mediapipe as mp

        self._mp = mp
        self._last_ts_ms = -1
        self.backend = None
        path = os.path.expanduser(model_path) if model_path else ""
        tasks_error = None

        if path and os.path.isfile(path):
            try:
                from mediapipe.tasks.python import BaseOptions, vision

                options = vision.HandLandmarkerOptions(
                    base_options=BaseOptions(model_asset_path=path),
                    running_mode=vision.RunningMode.VIDEO,
                    num_hands=1,
                    min_hand_detection_confidence=min_detection_confidence,
                    min_hand_presence_confidence=min_presence_confidence,
                    min_tracking_confidence=min_tracking_confidence,
                )
                self._landmarker = vision.HandLandmarker.create_from_options(options)
                self.backend = "tasks"
            except Exception as e:  # no Tasks API, or a corrupt / partial model file
                tasks_error = e
        else:
            tasks_error = FileNotFoundError("model file not found: %r" % (path or model_path))

        if self.backend is None:
            if not hasattr(mp, "solutions"):
                raise RuntimeError(
                    "MediaPipe Tasks API unusable (%s) and this MediaPipe has no "
                    "mp.solutions. Download the model:\n  %s\nand set model_path."
                    % (tasks_error, MODEL_URL))
            log("hand_tracker: Tasks API unusable (%s); using mp.solutions.hands"
                % tasks_error)
            self._hands = mp.solutions.hands.Hands(
                static_image_mode=False,
                max_num_hands=1,
                min_detection_confidence=min_detection_confidence,
                min_tracking_confidence=min_tracking_confidence,
            )
            self.backend = "solutions"

    def process(self, frame_bgr, now_s: float) -> Optional[List[Tuple[float, float]]]:
        """Landmarks of one hand as 21 normalized (x, y), or None if no hand.
        ``frame_bgr`` is an OpenCV BGR image (already mirrored)."""
        import cv2

        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        if self.backend == "tasks":
            # VIDEO mode needs strictly increasing timestamps.
            ts = max(int(now_s * 1000), self._last_ts_ms + 1)
            self._last_ts_ms = ts
            image = self._mp.Image(image_format=self._mp.ImageFormat.SRGB, data=rgb)
            result = self._landmarker.detect_for_video(image, ts)
            if not result.hand_landmarks:
                return None
            return [(lm.x, lm.y) for lm in result.hand_landmarks[0]]

        result = self._hands.process(rgb)
        if not result.multi_hand_landmarks:
            return None
        return [(lm.x, lm.y) for lm in result.multi_hand_landmarks[0].landmark]

    def close(self) -> None:
        try:
            if self.backend == "tasks":
                self._landmarker.close()
            elif self.backend == "solutions":
                self._hands.close()
        except Exception:
            pass
