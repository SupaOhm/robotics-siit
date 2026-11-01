"""AlertBot against a fake Telegram bot. Needs python-telegram-bot installed
(for the button classes and errors); skipped otherwise, e.g. in CI."""

import asyncio
from types import SimpleNamespace

import pytest

pytest.importorskip("telegram")

from telegram.error import BadRequest, NetworkError, TimedOut  # noqa: E402

from telegram_alert.bot import AlertBot  # noqa: E402
from telegram_alert.settings import Settings  # noqa: E402

CHAT = -100


class FakeBot:
    def __init__(self):
        self.calls = []
        self._next_id = 1
        self.fail = {}  # method name -> exception to raise once
        self.gate = None  # asyncio.Event a send waits on, to test ordering

    async def _sent(self, kind, **kw):
        if self.gate is not None:
            await self.gate.wait()
        if kind in self.fail:
            raise self.fail.pop(kind)
        self.calls.append((kind, kw))
        self._next_id += 1
        return SimpleNamespace(message_id=self._next_id)

    async def send_photo(self, **kw):
        return await self._sent("send_photo", **kw)

    async def send_message(self, **kw):
        return await self._sent("send_message", **kw)

    async def edit_message_caption(self, **kw):
        self.calls.append(("edit_message_caption", kw))

    async def edit_message_text(self, **kw):
        self.calls.append(("edit_message_text", kw))


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    async def no_wait(_):
        return None
    monkeypatch.setattr("telegram_alert.bot.asyncio.sleep", no_wait)


def make(allowed=()):
    decisions, warnings = [], []
    fake = FakeBot()
    bot = AlertBot(Settings("token", CHAT, frozenset(allowed)), decisions.append,
                   log=lambda _: None, warn=warnings.append, bot=fake)
    return bot, fake, decisions, warnings


def press(data, chat=CHAT, user_id=7, username="op"):
    answers = []

    async def answer(text=None, **kw):
        answers.append(text)

    query = SimpleNamespace(
        data=data,
        message=SimpleNamespace(chat=SimpleNamespace(id=chat)),
        from_user=SimpleNamespace(id=user_id, username=username, full_name="Op Erator"),
        answer=answer,
    )
    return SimpleNamespace(callback_query=query), answers


def buttons(call):
    return [b.callback_data for row in call[1]["reply_markup"].inline_keyboard for b in row]


def kinds(fake):
    return [k for k, _ in fake.calls]


def test_alert_with_photo_then_allow():
    bot, fake, decisions, _ = make()

    async def go():
        await bot.alert("a1", b"\xff\xd8jpeg")
        update, answers = press(buttons(fake.calls[0])[0])
        await bot.on_button(update, None)
        return answers

    answers = asyncio.run(go())
    kind, kw = fake.calls[0]
    assert kind == "send_photo" and kw["chat_id"] == CHAT and kw["photo"] == b"\xff\xd8jpeg"
    assert [b.split(":")[0] for b in buttons(fake.calls[0])] == ["allow", "deny"]
    assert decisions == [{"id": "a1", "decision": "allow"}]
    assert "@op" in answers[0]
    kind, kw = fake.calls[1]
    assert kind == "edit_message_caption" and "reply_markup" not in kw
    assert kw["message_id"] == 2 and "Allowed by @op" in kw["caption"]


def test_alert_without_photo_uses_text_message():
    bot, fake, _, _ = make()
    asyncio.run(bot.alert("a1", None, "(no camera image)"))
    kind, kw = fake.calls[0]
    assert kind == "send_message" and kw["text"].endswith("(no camera image)")


def test_photo_failure_falls_back_to_text():
    bot, fake, _, warnings = make()
    fake.fail["send_photo"] = BadRequest("Photo_invalid_dimensions")
    asyncio.run(bot.alert("a1", b"jpeg"))
    assert kinds(fake) == ["send_message"]
    assert "photo failed" in fake.calls[0][1]["text"]
    assert any("photo failed" in w for w in warnings)
    # the text card can still be closed later with edit_message_text
    asyncio.run(bot.blocking("a2"))
    assert kinds(fake)[1] == "edit_message_text"


def test_photo_timeout_still_sends_the_alert_as_text():
    # ohm's review on #6: a slow upload on the hotspot must not lose the alert
    bot, fake, decisions, warnings = make()
    fake.fail["send_photo"] = TimedOut()
    asyncio.run(bot.alert("a1", b"jpeg"))
    assert kinds(fake) == ["send_message"]  # the photo is not retried
    assert "photo upload timed out" in fake.calls[0][1]["text"]
    assert any("timed out" in w for w in warnings)
    # The photo may still have arrived with the same buttons: the first press
    # on either copy counts, and the second gets "no longer active".
    data = buttons(fake.calls[0])[0]

    async def go():
        await bot.on_button(press(data)[0], None)
        update, answers = press(data)
        await bot.on_button(update, None)
        return answers

    assert "no longer active" in asyncio.run(go())[0]
    assert decisions == [{"id": "a1", "decision": "allow"}]


def test_photo_upload_time_is_capped():
    bot, fake, _, _ = make()
    asyncio.run(bot.alert("a1", b"jpeg"))
    assert fake.calls[0][1]["write_timeout"] == 8.0


def test_timed_out_text_send_is_not_retried():
    bot, fake, _, warnings = make()
    fake.fail["send_message"] = TimedOut()
    asyncio.run(bot.alert("a1", None))
    assert kinds(fake) == []  # no duplicate text card
    assert any("may have arrived" in w for w in warnings)


def test_close_waits_for_a_send_in_flight():
    # ohm's review #7: blocking must not overtake the alert's send
    bot, fake, _, _ = make()

    async def go():
        fake.gate = asyncio.Event()
        sending = asyncio.ensure_future(bot.alert("a1", b"jpeg"))
        await asyncio.sleep(0)
        blocking = asyncio.ensure_future(bot.blocking("a2"))
        await asyncio.sleep(0)
        fake.gate.set()
        await asyncio.gather(sending, blocking)

    asyncio.run(go())
    assert kinds(fake) == ["send_photo", "edit_message_caption", "send_message"]
    assert "No answer in 30 s" in fake.calls[1][1]["caption"]


def test_timeout_then_resume():
    bot, fake, decisions, _ = make()

    async def go():
        await bot.alert("a1", b"jpeg")
        allow = buttons(fake.calls[0])[0]
        await bot.blocking("a2")  # state machine's 30 s timeout
        await bot.on_button(press(allow)[0], None)  # too late
        await bot.on_button(press(buttons(fake.calls[2])[0])[0], None)

    asyncio.run(go())
    assert kinds(fake) == ["send_photo", "edit_message_caption", "send_message",
                           "edit_message_text"]
    assert "No answer in 30 s" in fake.calls[1][1]["caption"]
    assert decisions == [{"id": "a2", "decision": "resume"}]


def test_robot_moving_on_closes_buttons():
    bot, fake, decisions, _ = make()

    async def go():
        await bot.alert("a1", b"jpeg")
        allow = buttons(fake.calls[0])[0]
        await bot.robot_state("WAIT_OPERATOR", "DRIVE")  # operator held back
        await bot.on_button(press(allow)[0], None)

    asyncio.run(go())
    assert kinds(fake) == ["send_photo", "edit_message_caption"]
    assert "now DRIVE" in fake.calls[1][1]["caption"]
    assert decisions == []


def test_press_from_other_chat_ignored():
    bot, fake, decisions, _ = make()

    async def go():
        await bot.alert("a1", b"jpeg")
        update, answers = press(buttons(fake.calls[0])[0], chat=999)
        await bot.on_button(update, None)
        return answers

    answers = asyncio.run(go())
    assert decisions == [] and answers == ["Not the operator chat"]
    assert all(card.open for card in bot.book.cards.values())


def test_user_without_username_shown_by_name():
    bot, fake, _, _ = make()

    async def go():
        await bot.alert("a1", b"jpeg")
        await bot.on_button(press(buttons(fake.calls[0])[1], username=None)[0], None)

    asyncio.run(go())
    assert "Denied by Op Erator" in fake.calls[1][1]["caption"]


def test_network_error_is_retried_and_bad_request_is_not():
    bot, _, _, _ = make()
    attempts = {"net": 0, "bad": 0}

    async def flaky():
        attempts["net"] += 1
        if attempts["net"] < 2:
            raise NetworkError("down")
        return "ok"

    async def bad():
        attempts["bad"] += 1
        raise BadRequest("Message is not modified")

    async def go():
        return await bot._call("flaky", flaky), await bot._call("bad", bad)

    assert asyncio.run(go()) == ("ok", None)
    assert attempts == {"net": 2, "bad": 1}
