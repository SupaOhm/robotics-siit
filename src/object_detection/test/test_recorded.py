from object_detection.recorded import answer, read_settings

SETTINGS = {"person": 0.25, "object": 0.5, "person_min_bottom": 0.0,
            "names": {"chair": "chair", "bottle": "bottle"}}


def test_settings_read_person_min_bottom(tmp_path):
    config = tmp_path / "detector.yaml"
    config.write_text('image_size: 320\nperson_threshold: 0.25\n'
                      'person_min_bottom: 0.8\nobject_threshold: 0.5\n'
                      'name_table:\n  - "chair=chair"\n')
    assert read_settings(str(config))["person_min_bottom"] == 0.8


def test_far_person_is_ignored_with_person_min_bottom():
    bottle = ["bottle", 0.9, 0.45, 0.5, 0.55, 0.99]
    far_person = ["person", 0.8, 0.7, 0.1, 0.8, 0.5]
    close = dict(SETTINGS, person_min_bottom=0.8)
    assert answer([bottle, far_person], SETTINGS) == "person"
    assert answer([bottle, far_person], close) == "bottle"


def test_saved_boxes_are_class_confidence_and_corners():
    # Corners are fractions of the frame: x1, y1, x2, y2. The bottle's
    # bottom edge (0.9) is lower than the chair's (0.5), so it's closer.
    bottle = ["bottle", 0.9, 0.45, 0.5, 0.55, 0.9]
    chair = ["chair", 0.8, 0.0, 0.0, 0.5, 0.5]
    assert answer([bottle, chair], SETTINGS) == "bottle"


def test_boxes_below_both_thresholds_are_dropped():
    weak_person = ["person", 0.2, 0.0, 0.0, 1.0, 1.0]
    bottle = ["bottle", 0.9, 0.45, 0.5, 0.55, 0.9]
    assert answer([weak_person, bottle], SETTINGS) == "bottle"
