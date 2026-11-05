"""Recordings of failed answers go to the operator only when the session is
denied (D32). A correct answer is never kept: it contains the password."""

from password_system.recordings import AttemptRecordings
from password_system.verifier import PasswordVerifier, make_stored, parse_stored


def session():
    h, salt, n = parse_stored(make_stored("1234", "salt"))
    verifier = PasswordVerifier(h, salt, n)
    verifier.start()
    return verifier, AttemptRecordings()


def test_three_wrong_answers_are_handed_over_when_denied():
    verifier, rec = session()
    assert rec.handle(b"one", verifier.submit(["1111"])) == []
    assert rec.handle(b"two", verifier.submit([])) == []  # unclear speech
    assert rec.handle(b"three", verifier.submit(["2222"])) == [(b"one", ""), (b"two", ""), (b"three", "")]
    assert rec.handle(b"later", verifier.submit(["3333"])) == []  # session over


def test_correct_answer_drops_everything():
    verifier, rec = session()
    rec.handle(b"wrong", verifier.submit(["1111"]))
    assert rec.handle(b"right", verifier.submit(["1234"])) == []
    assert rec.clips == []


def test_silence_has_no_recording():
    verifier, rec = session()
    rec.handle(b"", verifier.no_speech())
    rec.handle(b"wrong", verifier.submit(["1111"]))
    assert rec.handle(b"", verifier.no_speech()) == [(b"wrong", "")]


def test_denied_by_engine_failures_hands_over_what_was_heard():
    verifier, rec = session()
    rec.handle(b"wrong", verifier.submit(["1111"]))
    for _ in range(2):
        assert rec.handle(b"", verifier.service_error()) == []
    assert rec.handle(b"", verifier.service_error()) == [(b"wrong", "")]


def test_clear_forgets_a_cancelled_session():
    verifier, rec = session()
    rec.handle(b"wrong", verifier.submit(["1111"]))
    rec.clear()
    verifier.start()
    verifier.submit(["1111"])
    verifier.submit(["1111"])
    assert rec.handle(b"last", verifier.submit(["1111"])) == [(b"last", "")]


def test_what_was_heard_stays_with_its_answer():
    verifier, rec = session()
    rec.handle(b"one", verifier.submit(["1111"]), "1 1 1 1")
    rec.handle(b"two", verifier.submit([]))
    assert rec.handle(b"three", verifier.submit(["2222"]), "2 2 2 2") == [
        (b"one", "1 1 1 1"), (b"two", ""), (b"three", "2 2 2 2")]


def test_a_correct_answer_keeps_no_text():
    verifier, rec = session()
    rec.handle(b"wrong", verifier.submit(["1111"]), "1 1 1 1")
    assert rec.handle(b"right", verifier.submit(["1234"]), "1 2 3 4") == []
    assert rec.clips == []
