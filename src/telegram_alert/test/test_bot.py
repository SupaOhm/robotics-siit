"""AlertBot against a fake Telegram bot. Needs python-telegram-bot installed
(for the button classes); skipped otherwise, e.g. in CI."""

import asyncio
from types import SimpleNamespace

import pytest

pytest.importorskip("telegram")

from telegram_alert.bot import AlertBot  # noqa: E402
from telegram_alert.settings import Settings  # noqa: E402

CHAT = -100


class FakeBot:
    def __init__(self):
        self.calls = []
        self._next_id = 1

    async def _sent(self, kind, **kw):
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


def make(allowed=()):
    decisions = []
    fake = FakeBot()
    bot = AlertBot(Settings("token", CHAT, frozenset(allowed)), decisions.append,
                   log=lambda _: None, bot=fake)
    return bot, fake, decisions


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


def test_alert_with_photo_then_allow():
    bot, fake, decisions = make()

    async def go():
        await bot.alert("a1", b"\xff\xd8jpeg")
        update, answers = press("allow:a1")
        await bot.on_button(update, None)
        return answers

    answers = asyncio.run(go())
    kind, kw = fake.calls[0]
    assert kind == "send_photo" and kw["chat_id"] == CHAT and kw["photo"] == b"\xff\xd8jpeg"
    assert buttons(fake.calls[0]) == ["allow:a1", "deny:a1"]
    assert decisions == [{"id": "a1", "decision": "allow"}]
    assert "@op" in answers[0]
    kind, kw = fake.calls[1]
    assert kind == "edit_message_caption" and "reply_markup" not in kw
    assert kw["message_id"] == 2 and "Allowed by @op" in kw["caption"]


def test_alert_without_photo_uses_text_message():
    bot, fake, _ = make()
    asyncio.run(bot.alert("a1", None, "(no camera image)"))
    kind, kw = fake.calls[0]
    assert kind == "send_message" and kw["text"].endswith("(no camera image)")


def test_timeout_then_resume():
    bot, fake, decisions = make()

    async def go():
        await bot.alert("a1", b"jpeg")
        await bot.blocking("a2")  # state machine's 30 s timeout
        await bot.on_button(press("allow:a1")[0], None)  # too late
        await bot.on_button(press("resume:a2")[0], None)

    asyncio.run(go())
    kinds = [k for k, _ in fake.calls]
    assert kinds == ["send_photo", "edit_message_caption", "send_message", "edit_message_text"]
    assert "No answer in 30 s" in fake.calls[1][1]["caption"]
    assert buttons(fake.calls[2]) == ["resume:a2"]
    assert decisions == [{"id": "a2", "decision": "resume"}]


def test_press_from_other_chat_ignored():
    bot, fake, decisions = make()

    async def go():
        await bot.alert("a1", b"jpeg")
        update, answers = press("allow:a1", chat=999)
        await bot.on_button(update, None)
        return answers

    answers = asyncio.run(go())
    assert decisions == [] and answers == ["Not the operator chat"]
    assert bot.book.cards["a1"].open


def test_user_without_username_shown_by_name():
    bot, fake, _ = make()

    async def go():
        await bot.alert("a1", b"jpeg")
        await bot.on_button(press("deny:a1", username=None)[0], None)

    asyncio.run(go())
    assert "Denied by Op Erator" in fake.calls[1][1]["caption"]


def test_network_error_is_retried_and_bad_request_is_not(monkeypatch):
    from telegram.error import BadRequest, NetworkError
    bot, _, _ = make()
    attempts = {"net": 0, "bad": 0}

    async def flaky():
        attempts["net"] += 1
        if attempts["net"] < 2:
            raise NetworkError("down")
        return "ok"

    async def bad():
        attempts["bad"] += 1
        raise BadRequest("Message is not modified")

    async def no_wait(_):
        return None

    monkeypatch.setattr(asyncio, "sleep", no_wait)

    async def go():
        return await bot._call("flaky", flaky), await bot._call("bad", bad)

    assert asyncio.run(go()) == ("ok", None)
    assert attempts == {"net": 2, "bad": 1}
