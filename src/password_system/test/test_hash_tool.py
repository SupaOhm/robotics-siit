import pytest

from password_system.hash_tool import main
from password_system.verifier import EventType, PasswordVerifier, parse_stored


def test_prints_one_line_that_the_verifier_accepts(capsys):
    main(["four", "7", "one", "nine"])
    out = capsys.readouterr().out.strip()
    assert out.startswith("export ROBOT_PASSWORD_HASH=") and "\n" not in out
    password_hash, salt, chars = parse_stored(out.split("=", 1)[1])
    assert chars == 4
    v = PasswordVerifier(password_hash, salt, chars)
    v.start()
    assert [e.type for e in v.submit(["4 7 1 9"])] == [EventType.GRANTED]


def test_rejects_non_digits():
    with pytest.raises(SystemExit):
        main(["open", "sesame"])
