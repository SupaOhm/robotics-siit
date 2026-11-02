import pytest

from password_system.normalize import normalize


@pytest.mark.parametrize("text,expected", [
    ("one three five two", "1352"),
    ("One, Three. Five! Two?", "1352"),
    ("1 3 5 2", "1352"),
    ("1,352", "1352"),
    ("zero oh eight", "008"),
    ("two to too", "222"),
    ("Open Sesame", "opensesame"),
    ("", ""),
])
def test_normalize(text, expected):
    assert normalize(text) == expected


def test_english_words_need_word_boundaries():
    # "one" inside "phone" or "someone" must not become a digit
    assert normalize("phone someone") == "phonesomeone"
