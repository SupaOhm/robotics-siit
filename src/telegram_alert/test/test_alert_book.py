import pytest

from telegram_alert.alert_book import (ALERT, BLOCKING, EXPIRED_LINE, SUPERSEDED_LINE,
                                       AlertBook, callback_data, parse_callback)


def test_alert_card_has_allow_and_deny():
    book = AlertBook()
    closes, card = book.new_alert("a1", "12:00:00")
    assert closes == []
    assert card.kind == ALERT
    assert [data for _, data in card.buttons] == ["allow:a1", "deny:a1"]
    assert "a1" in card.text and "30 s" in card.text


@pytest.mark.parametrize("decision", ["allow", "deny"])
def test_press_alert_publishes_decision_and_closes(decision):
    book = AlertBook()
    book.new_alert("a1", "t")
    result = book.press("%s:a1" % decision, 7, "@op")
    assert result.decision == {"id": "a1", "decision": decision}
    assert result.close.card.alert_id == "a1"
    assert "@op" in result.close.text
    assert not book.cards["a1"].open


def test_second_press_is_ignored():
    book = AlertBook()
    book.new_alert("a1", "t")
    book.press("allow:a1", 7, "@op")
    result = book.press("deny:a1", 8, "@other")
    assert result.decision is None and result.close is None
    assert "no longer active" in result.toast


def test_blocking_expires_unanswered_alert():
    # 30 s timeout in the state machine -> /telegram/blocking with a new id
    book = AlertBook()
    book.new_alert("a1", "t")
    closes, card = book.new_blocking("a2", "t")
    assert len(closes) == 1
    assert closes[0].card.alert_id == "a1"
    assert closes[0].text.endswith(EXPIRED_LINE)
    assert card.kind == BLOCKING
    assert [data for _, data in card.buttons] == ["resume:a2"]
    # a late press on the expired card does nothing
    assert book.press("allow:a1", 7, "@op").decision is None


def test_blocking_after_deny_has_nothing_to_expire():
    book = AlertBook()
    book.new_alert("a1", "t")
    book.press("deny:a1", 7, "@op")
    closes, card = book.new_blocking("a2", "t")
    assert closes == []
    assert card is not None


def test_resume():
    book = AlertBook()
    book.new_blocking("a2", "t")
    result = book.press("resume:a2", 7, "@op")
    assert result.decision == {"id": "a2", "decision": "resume"}


def test_new_alert_supersedes_open_cards():
    book = AlertBook()
    book.new_blocking("a2", "t")
    closes, _ = book.new_alert("a3", "t")
    assert [c.card.alert_id for c in closes] == ["a2"]
    assert closes[0].text.endswith(SUPERSEDED_LINE)
    assert book.press("resume:a2", 7, "@op").decision is None


def test_new_blocking_supersedes_older_blocking():
    book = AlertBook()
    book.new_blocking("a2", "t")
    closes, _ = book.new_blocking("a4", "t")
    assert closes[0].text.endswith(SUPERSEDED_LINE)


def test_repeated_id_ignored():
    book = AlertBook()
    book.new_alert("a1", "t")
    assert book.new_alert("a1", "t") == ([], None)
    assert book.new_blocking("a1", "t") == ([], None)


def test_wrong_button_for_card_kind():
    book = AlertBook()
    book.new_alert("a1", "t")
    assert book.press("resume:a1", 7, "@op").decision is None
    assert book.cards["a1"].open


def test_unknown_buttons():
    book = AlertBook()
    assert book.press("", 7, "x").decision is None
    assert book.press("hello", 7, "x").decision is None
    assert book.press("allow:nope", 7, "x").decision is None


def test_allowed_users():
    book = AlertBook(allowed_users=[111])
    book.new_alert("a1", "t")
    result = book.press("allow:a1", 222, "@stranger")
    assert result.decision is None and "not allowed" in result.toast
    assert book.cards["a1"].open
    assert book.press("allow:a1", 111, "@op").decision is not None


def test_callback_data_roundtrip_and_limit():
    assert parse_callback(callback_data("deny", "a7")) == ("deny", "a7")
    assert parse_callback("allow:") is None
    assert parse_callback("explode:a1") is None
    with pytest.raises(ValueError):
        callback_data("allow", "x" * 64)


def test_old_cards_are_forgotten():
    book = AlertBook()
    for i in range(60):
        book.new_alert("a%d" % i, "t")
    assert len(book.cards) == 50
    assert "a0" not in book.cards and "a59" in book.cards
