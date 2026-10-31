import pytest

from password_system.normalize import normalize
from password_system.verifier import (EventType, PasswordVerifier, hash_password,
                                      outputs_for)

SALT = "testsalt"


def make(password="one three five two", attempts=3, match_mode="contains",
         max_service_errors=3):
    n = normalize(password)
    return PasswordVerifier(hash_password(n, SALT), SALT, len(n), attempts,
                            match_mode, max_service_errors)


def types(events):
    return [e.type for e in events]


def test_correct_password_granted():
    v = make()
    assert types(v.start()) == [EventType.STARTED]
    assert types(v.submit(["one three five two"])) == [EventType.GRANTED]
    assert not v.active


@pytest.mark.parametrize("heard", [
    "1352", "1 3 5 2", "One, three, five, two.", "1,352", "one 3 five to",
    "หนึ่ง สาม ห้า สอง", "๑๓๕๒",
])
def test_transcription_variants_match(heard):
    v = make()
    v.start()
    assert types(v.submit([heard])) == [EventType.GRANTED]


def test_contains_mode_allows_extra_words():
    v = make()
    v.start()
    assert types(v.submit(["the password is 1352 thanks"])) == [EventType.GRANTED]


def test_exact_mode_rejects_extra_words():
    v = make(match_mode="exact")
    v.start()
    assert types(v.submit(["the password is 1352"])) == [EventType.WRONG]
    assert types(v.submit(["1352"])) == [EventType.GRANTED]


def test_any_candidate_can_match():
    v = make()
    v.start()
    assert types(v.submit(["one tree five too", "1352"])) == [EventType.GRANTED]


def test_three_wrong_attempts_lock_out():
    v = make()
    v.start()
    assert types(v.submit(["1111"])) == [EventType.WRONG]
    assert v.attempts_left == 2
    assert types(v.submit(["hello"])) == [EventType.WRONG]
    assert types(v.submit(["2222"])) == [EventType.WRONG, EventType.LOCKED_OUT]
    assert not v.active
    assert v.attempts_left == 0


def test_correct_after_wrong():
    v = make()
    v.start()
    v.submit(["5555"])
    assert types(v.submit(["1352"])) == [EventType.GRANTED]


def test_silence_and_unclear_cost_attempts():
    v = make()
    v.start()
    assert types(v.no_speech()) == [EventType.NO_SPEECH]
    assert types(v.submit([])) == [EventType.UNCLEAR]
    assert types(v.submit(["  "])) == [EventType.UNCLEAR, EventType.LOCKED_OUT]


def test_service_errors_do_not_cost_attempts():
    v = make(max_service_errors=3)
    v.start()
    assert types(v.service_error()) == [EventType.SERVICE_ERROR]
    assert v.attempts_left == 3
    v.service_error()
    assert types(v.service_error()) == [EventType.SERVICE_ERROR, EventType.LOCKED_OUT]
    assert not v.active


def test_service_error_count_resets_after_good_listen():
    v = make(max_service_errors=2)
    v.start()
    v.service_error()
    v.submit(["9999"])
    assert types(v.service_error()) == [EventType.SERVICE_ERROR]
    assert v.active


def test_inactive_session_ignores_input():
    v = make()
    assert v.submit(["1352"]) == []
    assert v.no_speech() == []
    assert v.service_error() == []


def test_cancel():
    v = make()
    v.start()
    assert types(v.cancel()) == [EventType.CANCELLED]
    assert not v.active
    assert v.cancel() == []


def test_restart_resets_attempts():
    v = make()
    v.start()
    v.submit(["1111"])
    v.start()
    assert v.attempts_left == 3


def test_thai_phrase_password():
    v = make(password="เปิด ประตู")
    v.start()
    assert types(v.submit(["ช่วยเปิดประตูหน่อย"])) == [EventType.GRANTED]


def test_event_dict_has_no_transcript():
    v = make()
    ev = v.start()[0].to_dict()
    assert ev == {"type": "started", "attempts_left": 3}


def test_outputs_start_plays_prompt():
    v = make()
    assert outputs_for(v.start()) == ([], ["password_prompt"])


def test_outputs_wrong_and_silence_play_wrong():
    v = make()
    v.start()
    assert outputs_for(v.submit(["1111"])) == ([], ["password_wrong"])
    assert outputs_for(v.no_speech()) == ([], ["password_wrong"])


def test_outputs_last_failure_plays_only_denied():
    v = make()
    v.start()
    v.submit(["1111"])
    v.submit(["2222"])
    assert outputs_for(v.submit(["3333"])) == (["denied"], ["password_denied"])


def test_outputs_granted_and_cancelled_have_no_clip():
    # password_correct is played by the state machine (PASS), not this node
    v = make()
    v.start()
    assert outputs_for(v.submit(["1352"])) == (["granted"], [])
    v.start()
    assert outputs_for(v.cancel()) == (["cancelled"], [])


def test_outputs_service_errors():
    v = make(max_service_errors=2)
    v.start()
    assert outputs_for(v.service_error()) == ([], [])
    assert outputs_for(v.service_error()) == (["denied"], ["password_denied"])
