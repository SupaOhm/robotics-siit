import pytest

from object_detection.classifier import (Detection, classify, parse_name_table)

NAMES = {"chair": "chair", "dining table": "table", "bottle": "bottle"}


def box(name, confidence, bottom=0.9, left=0.4, right=0.6, top=0.5):
    """A detection whose box ends `bottom` of the way down the frame. The
    camera looks along the floor, so a lower bottom edge is closer."""
    return Detection(name, confidence, (left, top, right, bottom))


def run(*detections):
    return classify("d7", detections, NAMES, person_threshold=0.25,
                    object_threshold=0.5)


def test_object_in_name_table():
    assert run(box("chair", 0.82)) == {
        "id": "d7", "kind": "object", "label": "chair", "confidence": 0.82,
        "clip": "found_chair"}


def test_label_is_the_spoken_name_not_the_yolo_class():
    result = run(box("dining table", 0.7))
    assert result["label"] == "table"
    assert result["clip"] == "found_table"


def test_person_result():
    assert run(box("person", 0.91)) == {
        "id": "d7", "kind": "person", "label": "person", "confidence": 0.91,
        "clip": None}


def test_person_wins_over_a_stronger_closer_object():
    result = run(box("chair", 0.95, bottom=1.0),
                 box("person", 0.3, bottom=0.5, left=0.9, right=1.0))
    assert result["kind"] == "person"


def test_best_person_confidence_is_reported():
    result = run(box("person", 0.3), box("person", 0.8))
    assert result["confidence"] == 0.8


def test_person_below_threshold_does_not_count():
    result = run(box("person", 0.2))
    assert result["kind"] == "unknown"


def test_weak_person_does_not_hide_an_object():
    result = run(box("person", 0.2, bottom=1.0), box("chair", 0.8))
    assert result["label"] == "chair"


def test_closest_box_is_named_not_the_largest():
    # Photo bottle_5216: a bottle in front of a larger chair.
    result = run(box("bottle", 0.91, bottom=0.97, left=0.31, right=0.52, top=0.30),
                 box("chair", 0.69, bottom=0.82, left=0.39, right=0.87, top=0.01))
    assert result["label"] == "bottle"


def test_closest_box_is_named_not_the_most_confident():
    result = run(box("chair", 0.6, bottom=0.95), box("bottle", 0.9, bottom=0.6))
    assert result["label"] == "chair"


def test_weak_closer_box_does_not_hide_a_confident_object():
    # Photo IMG_5044: a confident bottle in front of a weak office chair.
    result = run(box("chair", 0.44, bottom=0.95), box("bottle", 0.83, bottom=0.8))
    assert result["label"] == "bottle"


def test_only_weak_boxes_is_unknown():
    result = run(box("chair", 0.4), box("bottle", 0.3))
    assert result["kind"] == "unknown"


def test_box_not_in_table_does_not_hide_a_named_object():
    # Recording bottle_front: at floor level the floor reads as a closer
    # "dining table", which would hide a clear bottle.
    result = run(box("couch", 0.9, bottom=1.0), box("chair", 0.9, bottom=0.7))
    assert result["label"] == "chair"


def test_only_boxes_not_in_table_is_unknown():
    result = run(box("couch", 0.9))
    assert result["kind"] == "unknown"


def test_nothing_detected_is_unknown():
    assert run() == {"id": "d7", "kind": "unknown", "label": None,
                     "confidence": 0.0, "clip": "found_obstacle"}


def run_close(*detections):
    """Only people whose box reaches 0.8 of the way down the frame count."""
    return classify("d7", detections, NAMES, person_threshold=0.25,
                    object_threshold=0.5, person_min_bottom=0.8)


def test_far_person_does_not_hide_the_object_in_front():
    # Photo IMG_5036: a bottle in front, a person walking past further back.
    result = run_close(box("bottle", 0.64, bottom=0.99),
                       box("person", 0.77, bottom=0.51, left=0.67, right=0.83))
    assert result["label"] == "bottle"


def test_close_person_counts_anywhere_across_the_frame():
    # At the edge of the robot's path, a person is near the side of the image.
    result = run_close(box("chair", 0.9, bottom=0.9),
                       box("person", 0.6, bottom=1.0, left=0.8, right=1.0))
    assert result["kind"] == "person"


def test_best_close_person_confidence_is_reported():
    result = run_close(box("person", 0.9, bottom=0.5), box("person", 0.4, bottom=0.95))
    assert result["confidence"] == 0.4


def test_person_min_bottom_is_inclusive():
    assert run_close(box("person", 0.5, bottom=0.8))["kind"] == "person"


def test_every_person_counts_by_default():
    # person_min_bottom 0: person first, whatever else is in frame (D8)
    result = run(box("bottle", 0.9, bottom=1.0), box("person", 0.3, bottom=0.1))
    assert result["kind"] == "person"


def test_threshold_is_inclusive():
    assert run(box("chair", 0.5))["kind"] == "object"
    assert run(box("person", 0.25))["kind"] == "person"


def test_parse_name_table():
    assert parse_name_table(["chair=chair", " dining table = table "]) == {
        "chair": "chair", "dining table": "table"}


@pytest.mark.parametrize("entry", ["chair", "=chair", "chair=", ""])
def test_parse_name_table_rejects_bad_lines(entry):
    with pytest.raises(ValueError):
        parse_name_table([entry])
