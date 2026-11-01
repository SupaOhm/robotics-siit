import json

from password_system.speech import VOSK_GRAMMAR, google_candidates, vosk_candidates


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


def test_vosk_unk_words_dropped():
    assert vosk_candidates(json.dumps({"text": "[unk] one three [unk] five two"})) == [
        "one three five two"]
    assert vosk_candidates(json.dumps({"text": "[unk]"})) == []


def test_vosk_grammar_is_digit_words():
    words = json.loads(VOSK_GRAMMAR)
    assert "[unk]" in words
    assert {"zero", "one", "two", "three", "four", "five", "six", "seven",
            "eight", "nine"} <= set(words)


def test_vosk_needs_a_model_folder(tmp_path):
    # no download at startup: the venue may have no internet (guy's review, #5)
    import pytest
    pytest.importorskip("speech_recognition")
    from password_system.speech import SpeechListener
    with pytest.raises(ValueError, match="vosk_model_path"):
        SpeechListener(engine="vosk", vosk_model_path="")
    with pytest.raises(ValueError, match="vosk_model_path"):
        SpeechListener(engine="vosk", vosk_model_path=str(tmp_path / "missing"))
