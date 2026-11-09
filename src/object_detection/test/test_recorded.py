from object_detection.recorded import answer

SETTINGS = {"person": 0.25, "object": 0.5,
            "names": {"chair": "chair", "bottle": "bottle"}}


def test_saved_boxes_are_class_confidence_and_corners():
    # Corners are fractions of the frame: x1, y1, x2, y2.
    bottle = ["bottle", 0.9, 0.45, 0.5, 0.55, 0.9]   # 0.1 x 0.4 = 0.04
    chair = ["chair", 0.8, 0.0, 0.0, 0.5, 0.5]       # 0.5 x 0.5 = 0.25
    assert answer([bottle, chair], SETTINGS) == "chair"


def test_boxes_below_both_thresholds_are_dropped():
    weak_person = ["person", 0.2, 0.0, 0.0, 1.0, 1.0]
    bottle = ["bottle", 0.9, 0.45, 0.5, 0.55, 0.9]
    assert answer([weak_person, bottle], SETTINGS) == "bottle"
