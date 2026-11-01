import pytest

from password_system.normalize import normalize
from types import SimpleNamespace

from password_system.verifier import (EventType, PasswordVerifier, hash_password,
                                      make_stored, outputs_for, parse_stored)

SALT = "testsalt"


def make(password="one three five two", attempts=3, match_mode="exact",
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
])
def test_transcription_variants_match(heard):
    v = make()
    v.start()
    assert types(v.submit([heard])) == [EventType.GRANTED]


def test_exact_is_the_default():
    v = PasswordVerifier(hash_password("1352", SALT), SALT, 4)
    assert v.match_mode == "exact"


def test_exact_mode_rejects_a_run_of_digits():
    # contains mode would let one attempt test many codes (guy's review, #5)
    v = make()
    v.start()
    assert types(v.submit(["0123135296"])) == [EventType.WRONG]
    assert types(v.submit(["the password is 1352"])) == [EventType.WRONG]
    assert types(v.submit(["1352"])) == [EventType.GRANTED]


def test_contains_mode_allows_extra_words():
    v = make(match_mode="contains")
    v.start()
    assert types(v.submit(["the password is 1352 thanks"])) == [EventType.GRANTED]


def test_max_service_errors_must_be_positive():
    with pytest.raises(ValueError):
        make(max_service_errors=0)


def test_stored_password_roundtrip():
    stored = make_stored("1352", "abc")
    password_hash, salt, chars = parse_stored(stored)
    assert (salt, chars) == ("abc", 4)
    v = PasswordVerifier(password_hash, salt, chars)
    v.start()
    assert types(v.submit(["one three five two"])) == [EventType.GRANTED]


@pytest.mark.parametrize("value", ["", "abc", "4:salt", "0:salt:" + "a" * 64,
                                   "x:salt:" + "a" * 64, "4::" + "a" * 64, "4:salt:abc"])
def test_bad_stored_password_fails_clearly(value):
    with pytest.raises(ValueError, match="make_password_hash"):
        parse_stored(value)


@pytest.mark.parametrize("kind,candidates,expected", [
    ("speech", ["1352"], [EventType.GRANTED]),
    ("speech", ["9999"], [EventType.WRONG]),
    ("speech", [], [EventType.UNCLEAR]),
    ("no_speech", [], [EventType.NO_SPEECH]),
    ("error", [], [EventType.SERVICE_ERROR]),
])
def test_handle_listen_result(kind, candidates, expected):
    v = make()
    v.start()
    assert types(v.handle(SimpleNamespace(kind=kind, candidates=candidates))) == expected


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
