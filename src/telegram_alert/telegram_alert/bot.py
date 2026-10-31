"""Telegram side of the alert flow (python-telegram-bot, long polling, D26).

``AlertBot`` sends and edits the cards that ``AlertBook`` decides on and
turns button presses into decisions. It runs on an asyncio loop. The ROS
node and the laptop demo both use it.
"""

import asyncio
import time
from typing import Callable, Iterable, Optional

from .alert_book import AlertBook, Card, Close

TRIES = 3


def _seconds(retry_after) -> float:
    # RetryAfter.retry_after is an int or a timedelta, depending on the version
    if hasattr(retry_after, "total_seconds"):
        return retry_after.total_seconds()
    return float(retry_after)


def _clock() -> str:
    return time.strftime("%H:%M:%S")


class AlertBot:
    def __init__(self, settings, on_decision: Callable[[dict], None],
                 log: Callable[[str], None] = print, bot=None):
        self.settings = settings
        self.book = AlertBook(settings.allowed_users)
        self.on_decision = on_decision
        self.log = log
        self.app = None
        self._bot = bot  # tests pass a fake; otherwise the Application's bot

    @property
    def bot(self):
        return self._bot if self._bot is not None else self.app.bot

    async def start(self) -> None:
        from telegram.ext import Application, CallbackQueryHandler, CommandHandler
        self.app = Application.builder().token(self.settings.token).build()
        self.app.add_handler(CallbackQueryHandler(self.on_button))
        self.app.add_handler(CommandHandler("start", self.on_start_command))
        await self.app.initialize()
        await self.app.start()
        # Old button presses from before a restart are dropped.
        await self.app.updater.start_polling(
            allowed_updates=["message", "callback_query"], drop_pending_updates=True)
        self.log("Telegram bot polling (chat %d)" % self.settings.chat_id)

    async def stop(self) -> None:
        if self.app is None:
            return
        if self.app.updater.running:
            await self.app.updater.stop()
        if self.app.running:
            await self.app.stop()
        await self.app.shutdown()

    # ----- state machine -> Telegram -------------------------------------

    async def alert(self, alert_id: str, jpeg: Optional[bytes] = None, note: str = "") -> None:
        """Photo of the person with Allow / Deny buttons."""
        closes, card = self.book.new_alert(alert_id, _clock())
        await self._close(closes)
        if card is None:
            self.log("alert %s already sent, ignored" % alert_id)
            return
        if note:
            card.text += "\n" + note
        card.with_photo = jpeg is not None
        await self._show(card, jpeg)

    async def blocking(self, alert_id: str) -> None:
        """Deny or timeout happened: expire Allow / Deny, offer Resume."""
        closes, card = self.book.new_blocking(alert_id, _clock())
        await self._close(closes)
        if card is None:
            self.log("blocking %s already sent, ignored" % alert_id)
            return
        await self._show(card, None)

    # ----- Telegram -> state machine -------------------------------------

    async def on_button(self, update, context) -> None:
        query = update.callback_query
        message = query.message
        if message is None or message.chat.id != self.settings.chat_id:
            await self._call("answer", lambda: query.answer("Not the operator chat"))
            return
        user = query.from_user
        name = "@" + user.username if user.username else user.full_name
        result = self.book.press(query.data, user.id, name)
        if result.decision is not None:
            self.on_decision(result.decision)  # first, so the robot reacts at once
            self.log("decision %s" % result.decision)
        await self._call("answer", lambda: query.answer(result.toast))
        if result.close is not None:
            await self._close([result.close])

    async def on_start_command(self, update, context) -> None:
        chat = update.effective_chat
        await self._call("reply", lambda: update.effective_message.reply_text(
            "Robot alert bot. This chat's id is %d.\n"
            "Set TELEGRAM_CHAT_ID=%d on the robot to get alerts here." % (chat.id, chat.id)))

    # ----- helpers --------------------------------------------------------

    def _markup(self, card: Card):
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup
        return InlineKeyboardMarkup(
            [[InlineKeyboardButton(label, callback_data=data) for label, data in card.buttons]])

    async def _show(self, card: Card, jpeg: Optional[bytes]) -> None:
        chat, markup = self.settings.chat_id, self._markup(card)
        if card.with_photo:
            msg = await self._call("send photo", lambda: self.bot.send_photo(
                chat_id=chat, photo=jpeg, caption=card.text, reply_markup=markup))
        else:
            msg = await self._call("send message", lambda: self.bot.send_message(
                chat_id=chat, text=card.text, reply_markup=markup))
        if msg is not None:
            card.message_id = msg.message_id

    async def _close(self, closes: Iterable[Close]) -> None:
        """Edit each card's text; leaving out reply_markup removes the buttons."""
        chat = self.settings.chat_id
        for close in closes:
            card = close.card
            if card.message_id is None:
                continue  # it was never delivered
            if card.with_photo:
                await self._call("edit caption", lambda: self.bot.edit_message_caption(
                    chat_id=chat, message_id=card.message_id, caption=close.text))
            else:
                await self._call("edit message", lambda: self.bot.edit_message_text(
                    text=close.text, chat_id=chat, message_id=card.message_id))

    async def _call(self, what: str, make_request):
        """Run a Telegram request, retrying network trouble. None on failure."""
        from telegram.error import BadRequest, NetworkError, RetryAfter, TelegramError
        for attempt in range(TRIES):
            try:
                return await make_request()
            except RetryAfter as e:
                await asyncio.sleep(_seconds(e.retry_after))
            except BadRequest as e:  # a subclass of NetworkError, but retrying won't help
                self.log("%s failed: %s" % (what, e))
                return None
            except NetworkError as e:
                self.log("%s: network error (%s), try %d/%d" % (what, e, attempt + 1, TRIES))
                await asyncio.sleep(1 + attempt)
            except TelegramError as e:
                self.log("%s failed: %s" % (what, e))
                return None
        self.log("%s failed after %d tries" % (what, TRIES))
        return None
