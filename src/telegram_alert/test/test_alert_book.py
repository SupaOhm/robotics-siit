import pytest

from telegram_alert.alert_book import (ALERT, BLOCKING, EXPIRED_LINE, SUPERSEDED_LINE,
                                       AlertBook, callback_data, parse_callback)


def button(card, decision):
    """The callback_data of ``card``'s button for ``decision``."""
    return next(data for _, data in card.buttons if data.startswith(decision + ":"))


def test_alert_card_has_allow_and_deny():
    book = AlertBook()
    closes, card = book.new_alert("a1", "12:00:00")
    assert closes == []
    assert card.kind == ALERT
    assert [parse_callback(d)[:2] for _, d in card.buttons] == [("allow", "a1"), ("deny", "a1")]
    assert "a1" in card.text and "30 s" in card.text


def test_alert_text_is_neutral_and_uses_the_timeout():
    # WAIT_OPERATOR also follows a password check with no result in 60 s (D30)
    _, card = AlertBook(timeout_s=45).new_alert("a1", "t")
    assert "3 times" not in card.text and "45 s" in card.text


@pytest.mark.parametrize("decision", ["allow", "deny"])
def test_press_alert_publishes_decision_and_closes(decision):
    book = AlertBook()
    _, card = book.new_alert("a1", "t")
    result = book.press(button(card, decision), 7, "@op")
    assert result.decision == {"id": "a1", "decision": decision}
    assert result.close.card is card
    assert "@op" in result.close.text
    assert not card.open


def test_second_press_is_ignored():
    book = AlertBook()
    _, card = book.new_alert("a1", "t")
    book.press(button(card, "allow"), 7, "@op")
    result = book.press(button(card, "deny"), 8, "@other")
    assert result.decision is None and result.close is None
    assert "no longer active" in result.toast


def test_blocking_expires_unanswered_alert():
    # 30 s timeout in the state machine -> /telegram/blocking with a new id
    book = AlertBook()
    _, alert = book.new_alert("a1", "t")
    closes, card = book.new_blocking("a2", "t")
    assert len(closes) == 1
    assert closes[0].card is alert
    assert closes[0].text.endswith(EXPIRED_LINE % 30)
    assert card.kind == BLOCKING
    assert [parse_callback(d)[:2] for _, d in card.buttons] == [("resume", "a2")]
    # a late press on the expired card does nothing
    assert book.press(button(alert, "allow"), 7, "@op").decision is None


def test_blocking_after_deny_has_nothing_to_expire():
    book = AlertBook()
    _, alert = book.new_alert("a1", "t")
    book.press(button(alert, "deny"), 7, "@op")
    closes, card = book.new_blocking("a2", "t")
    assert closes == []
    assert card is not None


def test_resume():
    book = AlertBook()
    _, card = book.new_blocking("a2", "t")
    result = book.press(button(card, "resume"), 7, "@op")
    assert result.decision == {"id": "a2", "decision": "resume"}


def test_new_alert_supersedes_open_cards():
    book = AlertBook()
    _, blocking = book.new_blocking("a2", "t")
    closes, _ = book.new_alert("a3", "t")
    assert [c.card for c in closes] == [blocking]
    assert closes[0].text.endswith(SUPERSEDED_LINE)
    assert book.press(button(blocking, "resume"), 7, "@op").decision is None


def test_new_blocking_supersedes_older_blocking():
    book = AlertBook()
    book.new_blocking("a2", "t")
    closes, _ = book.new_blocking("a4", "t")
    assert closes[0].text.endswith(SUPERSEDED_LINE)


def test_duplicate_of_open_card_ignored():
    book = AlertBook()
    book.new_alert("a1", "t")
    assert book.new_alert("a1", "t") == ([], None)


def test_reused_id_after_state_machine_restart_gets_a_new_card():
    # ids may restart at a1 (ohm's review, #6): the old button must not
    # approve the new alert, and the new alert must still be sent
    book = AlertBook()
    _, old = book.new_alert("a1", "t")
    book.press(button(old, "deny"), 7, "@op")
    closes, new = book.new_alert("a1", "t")
    assert new is not None and new.token != old.token
    assert book.press(button(old, "allow"), 7, "@op").decision is None
    assert new.open
    assert book.press(button(new, "allow"), 7, "@op").decision == {
        "id": "a1", "decision": "allow"}


def test_open_alert_then_reused_id_closes_the_old_card():
    book = AlertBook()
    _, old = book.new_alert("a1", "t")
    book.new_blocking("a2", "t")  # old alert expires
    closes, new = book.new_alert("a1", "t")
    assert new is not None and not old.open


def test_buttons_differ_between_runs():
    a = AlertBook().new_alert("a1", "t")[1]
    b = AlertBook().new_alert("a1", "t")[1]
    assert a.buttons != b.buttons


def test_leaving_wait_operator_closes_the_alert():
    # e.g. the operator holds `back` during WAIT_OPERATOR (D11)
    book = AlertBook()
    _, card = book.new_alert("a1", "t")
    closes = book.state_changed("WAIT_OPERATOR", "DRIVE")
    assert [c.card for c in closes] == [card]
    assert closes[0].text.endswith("now DRIVE)")
    assert book.press(button(card, "allow"), 7, "@op").decision is None


def test_wait_operator_to_blocking_is_left_to_the_blocking_message():
    book = AlertBook()
    _, card = book.new_alert("a1", "t")
    assert book.state_changed("WAIT_OPERATOR", "BLOCKING") == []
    assert card.open
    closes, _ = book.new_blocking("a2", "t")
    assert closes[0].text.endswith(EXPIRED_LINE % 30)


def test_leaving_blocking_closes_resume():
    # `back` held 1 s in BLOCKING -> AVOID (D11)
    book = AlertBook()
    _, card = book.new_blocking("a2", "t")
    assert [c.card for c in book.state_changed("BLOCKING", "AVOID")] == [card]


def test_other_state_changes_close_nothing():
    book = AlertBook()
    _, card = book.new_alert("a1", "t")
    assert book.state_changed("CHECKPOINT", "WAIT_OPERATOR") == []
    assert book.state_changed("DRIVE", "CLASSIFY") == []
    assert card.open


def test_wrong_button_for_card_kind():
    book = AlertBook()
    _, card = book.new_alert("a1", "t")
    fake_resume = callback_data("resume", "a1", card.token)
    assert book.press(fake_resume, 7, "@op").decision is None
    assert card.open


def test_unknown_buttons():
    book = AlertBook()
    _, card = book.new_alert("a1", "t")
    assert book.press("", 7, "x").decision is None
    assert book.press("hello", 7, "x").decision is None
    assert book.press("allow:a1", 7, "x").decision is None  # old format, no token
    assert book.press(callback_data("allow", "a1", "nope"), 7, "x").decision is None
    assert book.press(callback_data("allow", "a9", card.token), 7, "x").decision is None


def test_allowed_users():
    book = AlertBook(allowed_users=[111])
    _, card = book.new_alert("a1", "t")
    result = book.press(button(card, "allow"), 222, "@stranger")
    assert result.decision is None and "not allowed" in result.toast
    assert card.open
    assert book.press(button(card, "allow"), 111, "@op").decision is not None


def test_callback_data_roundtrip_and_limit():
    assert parse_callback(callback_data("deny", "a7", "k1")) == ("deny", "a7", "k1")
    assert parse_callback(callback_data("allow", "id:with:colons", "k1")) == (
        "allow", "id:with:colons", "k1")
    assert parse_callback("allow:k1:") is None
    assert parse_callback("explode:k1:a1") is None
    with pytest.raises(ValueError):
        callback_data("allow", "x" * 64, "k1")


def test_old_cards_are_forgotten():
    book = AlertBook()
    for i in range(60):
        book.new_alert("a%d" % i, "t")
    assert len(book.cards) == 50
    assert all(c.alert_id != "a0" for c in book.cards.values())
