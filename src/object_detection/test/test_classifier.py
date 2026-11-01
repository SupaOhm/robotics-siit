import pytest

from object_detection.classifier import (Detection, classify, parse_name_table)

NAMES = {"chair": "chair", "dining table": "table", "bottle": "bottle"}


def run(*detections):
    return classify("d7", detections, NAMES, person_threshold=0.25,
                    object_threshold=0.5)


def test_object_in_name_table():
    assert run(Detection("chair", 0.82, 500)) == {
        "id": "d7", "kind": "object", "label": "chair", "confidence": 0.82,
        "clip": "found_chair"}


def test_label_is_the_spoken_name_not_the_yolo_class():
    result = run(Detection("dining table", 0.7, 500))
    assert result["label"] == "table"
    assert result["clip"] == "found_table"


def test_person_result():
    assert run(Detection("person", 0.91, 500)) == {
        "id": "d7", "kind": "person", "label": "person", "confidence": 0.91,
        "clip": None}


def test_person_wins_over_a_stronger_larger_object():
    result = run(Detection("chair", 0.95, 9000), Detection("person", 0.3, 10))
    assert result["kind"] == "person"


def test_best_person_confidence_is_reported():
    result = run(Detection("person", 0.3, 900), Detection("person", 0.8, 10))
    assert result["confidence"] == 0.8


def test_person_below_threshold_does_not_count():
    result = run(Detection("person", 0.2, 500))
    assert result["kind"] == "unknown"


def test_weak_person_does_not_hide_an_object():
    result = run(Detection("person", 0.2, 9000), Detection("chair", 0.8, 500))
    assert result["label"] == "chair"


def test_largest_box_is_named_not_the_most_confident():
    result = run(Detection("chair", 0.6, 9000), Detection("bottle", 0.9, 100))
    assert result["label"] == "chair"


def test_largest_box_below_threshold_is_unknown():
    result = run(Detection("chair", 0.4, 9000), Detection("bottle", 0.9, 100))
    assert result["kind"] == "unknown"


def test_largest_box_not_in_table_is_unknown():
    result = run(Detection("couch", 0.9, 9000), Detection("chair", 0.9, 100))
    assert result["kind"] == "unknown"


def test_nothing_detected_is_unknown():
    assert run() == {"id": "d7", "kind": "unknown", "label": None,
                     "confidence": 0.0, "clip": "found_obstacle"}


def test_threshold_is_inclusive():
    assert run(Detection("chair", 0.5, 500))["kind"] == "object"
    assert run(Detection("person", 0.25, 500))["kind"] == "person"


def test_parse_name_table():
    assert parse_name_table(["chair=chair", " dining table = table "]) == {
        "chair": "chair", "dining table": "table"}


@pytest.mark.parametrize("entry", ["chair", "=chair", "chair=", ""])
def test_parse_name_table_rejects_bad_lines(entry):
    with pytest.raises(ValueError):
        parse_name_table([entry])
