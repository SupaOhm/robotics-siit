"""Run the YOLO model on one frame.

Ultralytics is only imported by ``YoloDetector`` so the rest of the package
can be tested without it.
"""

import os
from typing import List

from .classifier import Detection


def resolve_model_path(model_path: str) -> str:
    """Return the model's full path, with a clear error if it doesn't exist."""
    path = os.path.abspath(os.path.expanduser(model_path))
    if not os.path.exists(path):
        raise FileNotFoundError(
            "YOLO model not found at %r. Export it first: see Setup in the "
            "object_detection README." % path)
    return path


class YoloDetector:
    """Wraps an Ultralytics model; returns the detections in a BGR frame."""

    def __init__(self, model_path: str, image_size: int, confidence: float):
        path = resolve_model_path(model_path)
        import numpy as np
        from ultralytics import YOLO  # lazy: only needed on a real camera
        self._model = YOLO(path, task="detect")
        self._image_size = image_size
        self._confidence = confidence
        # The model loads on first use. Do that now, so the first real request
        # doesn't run out the state machine's 3 s timeout.
        self.detect(np.zeros((image_size, image_size, 3), dtype=np.uint8))

    def detect(self, bgr_image) -> List[Detection]:
        result = self._model.predict(bgr_image, imgsz=self._image_size,
                                     conf=self._confidence, verbose=False)[0]
        detections = []
        for box in result.boxes:
            x1, y1, x2, y2 = box.xyxy[0].tolist()
            detections.append(Detection(result.names[int(box.cls[0])],
                                        float(box.conf[0]),
                                        (x2 - x1) * (y2 - y1)))
        return detections
