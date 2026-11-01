import pytest

from telegram_alert.settings import load_settings, parse_env_file, parse_user_ids


def test_parse_env_file():
    text = """
# comment
TELEGRAM_BOT_TOKEN=123:abc
export TELEGRAM_CHAT_ID="-1001234"
TELEGRAM_ALLOWED_USERS = '11, 22'
not a line
"""
    assert parse_env_file(text) == {
        "TELEGRAM_BOT_TOKEN": "123:abc",
        "TELEGRAM_CHAT_ID": "-1001234",
        "TELEGRAM_ALLOWED_USERS": "11, 22",
    }


def test_parse_user_ids():
    assert parse_user_ids("11, 22,") == frozenset({11, 22})
    assert parse_user_ids("") == frozenset()


def test_load_from_environ():
    s = load_settings({"TELEGRAM_BOT_TOKEN": "t", "TELEGRAM_CHAT_ID": "-5"})
    assert (s.token, s.chat_id, s.allowed_users) == ("t", -5, frozenset())


def test_env_file_fills_missing_values_only(tmp_path):
    env = tmp_path / ".env"
    env.write_text("TELEGRAM_BOT_TOKEN=from_file\nTELEGRAM_CHAT_ID=42\n", encoding="utf-8")
    s = load_settings({"TELEGRAM_BOT_TOKEN": "from_env"}, env_file=str(env))
    assert s.token == "from_env" and s.chat_id == 42


@pytest.mark.parametrize("environ", [
    {},
    {"TELEGRAM_BOT_TOKEN": "t"},
    {"TELEGRAM_CHAT_ID": "1"},
])
def test_missing_values_fail(environ):
    with pytest.raises(RuntimeError):
        load_settings(environ)


def test_bad_numbers_fail():
    with pytest.raises(RuntimeError):
        load_settings({"TELEGRAM_BOT_TOKEN": "t", "TELEGRAM_CHAT_ID": "abc"})


def test_inline_comments():
    text = ('TELEGRAM_CHAT_ID=-100123  # operator group\n'
            'TELEGRAM_BOT_TOKEN="a #b"\n'
            'TELEGRAM_ALLOWED_USERS="11,22" # pun and fah\n'
            "OTHER='x' # note\n")
    assert parse_env_file(text) == {"TELEGRAM_CHAT_ID": "-100123",
                                    "TELEGRAM_BOT_TOKEN": "a #b",
                                    "TELEGRAM_ALLOWED_USERS": "11,22",
                                    "OTHER": "x"}


def test_token_not_in_repr():
    s = load_settings({"TELEGRAM_BOT_TOKEN": "secret123", "TELEGRAM_CHAT_ID": "1"})
    assert "secret123" not in repr(s)
