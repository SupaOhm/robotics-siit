import json

from password_system.speech import google_candidates, vosk_candidates


def test_google_candidates():
    response = {
        "alternative": [
            {"transcript": "1352", "confidence": 0.9},
            {"transcript": "one three five two"},
        ],
        "final": True,
    }
    assert google_candidates(response) == ["1352", "one three five two"]


def test_google_nothing_recognized():
    assert google_candidates([]) == []
    assert google_candidates({"alternative": []}) == []


def test_vosk_single_result():
    assert vosk_candidates(json.dumps({"text": "one three five two"})) == [
        "one three five two"]
    assert vosk_candidates(json.dumps({"text": ""})) == []


def test_vosk_alternatives():
    data = {"alternatives": [{"confidence": 200.0, "text": "one three five two"},
                             {"confidence": 150.0, "text": "one three five to"},
                             {"confidence": 10.0, "text": ""}]}
    assert vosk_candidates(json.dumps(data)) == ["one three five two",
                                                 "one three five to"]
