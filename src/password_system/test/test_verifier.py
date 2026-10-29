from password_system.verifier import EventType, PasswordVerifier, hash_password

SALT = "testsalt"


def make(password="1352", attempts=3, timeout=15.0):
    return PasswordVerifier(hash_password(password, SALT), SALT, len(password),
                            attempts, timeout)


def enter(v, code, t=0.0):
    events = []
    for i, c in enumerate(code):
        events += v.feed(c, t + i)
    return [e.type for e in events]


def test_correct_password_granted():
    v = make()
    assert [e.type for e in v.start(0.0)] == [EventType.STARTED]
    types = enter(v, "1352")
    assert types[-1] == EventType.GRANTED
    assert not v.active


def test_three_wrong_attempts_lock_out():
    v = make()
    v.start(0.0)
    assert enter(v, "1111")[-1] == EventType.WRONG
    assert v.attempts_left == 2
    assert enter(v, "2222")[-1] == EventType.WRONG
    types = enter(v, "3333")
    assert types[-2:] == [EventType.WRONG, EventType.LOCKED_OUT]
    assert not v.active
    assert v.attempts_left == 0


def test_correct_after_wrong():
    v = make()
    v.start(0.0)
    enter(v, "5555")
    assert enter(v, "1352")[-1] == EventType.GRANTED


def test_wrong_attempt_clears_partial_input():
    v = make()
    v.start(0.0)
    enter(v, "4444")
    assert v.tokens_entered == 0


def test_input_timeout_costs_attempt():
    v = make(timeout=10.0)
    v.start(0.0)
    assert v.tick(9.9) == []
    assert [e.type for e in v.tick(10.0)] == [EventType.ATTEMPT_TIMEOUT]
    assert v.attempts_left == 2
    v.tick(20.0)
    types = [e.type for e in v.tick(30.0)]
    assert types == [EventType.ATTEMPT_TIMEOUT, EventType.LOCKED_OUT]


def test_timeout_resets_on_input():
    v = make(timeout=10.0)
    v.start(0.0)
    v.feed("1", 8.0)
    assert v.tick(15.0) == []


def test_feed_ignored_when_inactive():
    v = make()
    assert v.feed("1", 0.0) == []
    assert v.tick(100.0) == []


def test_cancel():
    v = make()
    v.start(0.0)
    v.feed("1", 1.0)
    assert [e.type for e in v.cancel()] == [EventType.CANCELLED]
    assert not v.active
    assert v.cancel() == []


def test_restart_resets_attempts():
    v = make()
    v.start(0.0)
    enter(v, "1111")
    v.start(10.0)
    assert v.attempts_left == 3


def test_event_does_not_leak_digits():
    v = make()
    v.start(0.0)
    ev = v.feed("1", 0.0)[0].to_dict()
    assert "1" not in [str(x) for x in ev.values() if isinstance(x, str)]
    assert ev["tokens_entered"] == 1
