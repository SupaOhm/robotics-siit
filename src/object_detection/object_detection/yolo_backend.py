"""Run the YOLO model on one frame.

Ultralytics is only imported by ``YoloDetector`` so the rest of the package
can be tested without it.
"""

from typing import List

from .classifier import Detection


class YoloDetector:
    """Wraps an Ultralytics model; returns the detections in a BGR frame."""

    def __init__(self, model_path: str, image_size: int, confidence: float):
        import numpy as np
        from ultralytics import YOLO  # lazy: only needed on a real camera
        self._model = YOLO(model_path, task="detect")
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
