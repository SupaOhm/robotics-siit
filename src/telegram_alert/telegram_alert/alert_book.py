"""Telegram alert bookkeeping (no ROS, no Telegram library).

Decides which Telegram messages ("cards") to send, which to close, and what a
button press means. ``bot.py`` does the actual Telegram calls.

Contract (docs/interfaces.md v0.3, D11, D14, D15):
- /telegram/alert <id>     -> card with a photo and Allow / Deny buttons
- /telegram/blocking <id>  -> card "Robot is blocking" with a Resume button.
  It also closes any Allow / Deny card nobody answered: the 30 s timeout
  lives in the state machine, which treats it as Deny.
- a button press           -> {"id": ..., "decision": "allow"|"deny"|"resume"}
  on /telegram/decision, and the card's buttons are removed.
"""

from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Iterable, List, Optional, Tuple

ALLOW, DENY, RESUME = "allow", "deny", "resume"
ALERT, BLOCKING = "alert", "blocking"
DECISIONS_FOR_KIND = {ALERT: (ALLOW, DENY), BLOCKING: (RESUME,)}
BUTTON_LABELS = {ALLOW: "✅ Allow", DENY: "⛔ Deny", RESUME: "▶️ Resume"}
RESULT_LINES = {ALLOW: "✅ Allowed by %s", DENY: "⛔ Denied by %s",
                RESUME: "▶️ Resumed by %s"}

EXPIRED_LINE = "⌛ No answer in 30 s: treated as Deny"
SUPERSEDED_LINE = "Closed: a newer alert replaced this one"

MAX_CALLBACK_BYTES = 64  # Telegram limit for callback_data
MAX_CARDS = 50


def callback_data(decision: str, alert_id: str) -> str:
    data = "%s:%s" % (decision, alert_id)
    if len(data.encode("utf-8")) > MAX_CALLBACK_BYTES:
        raise ValueError("alert id too long for a Telegram button: %r" % alert_id)
    return data


def parse_callback(data: str) -> Optional[Tuple[str, str]]:
    """'allow:a3' -> ('allow', 'a3'); None if it isn't one of our buttons."""
    decision, sep, alert_id = (data or "").partition(":")
    if not sep or not alert_id or decision not in BUTTON_LABELS:
        return None
    return decision, alert_id


def alert_text(alert_id: str, clock: str) -> str:
    return ("🚨 Checkpoint: wrong password 3 times.\n"
            "Alert %s at %s\n"
            "Allow this person to pass? No answer in 30 s = Deny." % (alert_id, clock))


def blocking_text(alert_id: str, clock: str) -> str:
    return ("🛑 Robot is blocking the person.\n"
            "Alert %s at %s\n"
            "Press Resume to let the robot turn away and continue." % (alert_id, clock))


@dataclass
class Card:
    """One Telegram message with buttons."""
    alert_id: str
    kind: str                       # ALERT | BLOCKING
    text: str
    buttons: List[Tuple[str, str]]  # (label, callback_data)
    with_photo: bool = False
    message_id: Optional[int] = None
    open: bool = True


@dataclass
class Close:
    """Edit ``card`` to ``text`` and remove its buttons."""
    card: Card
    text: str


@dataclass
class PressResult:
    toast: str                      # short pop-up shown to whoever pressed
    decision: Optional[dict] = None  # publish this on /telegram/decision
    close: Optional[Close] = None


@dataclass
class AlertBook:
    allowed_users: Iterable[int] = ()
    cards: "OrderedDict[str, Card]" = field(default_factory=OrderedDict)

    def __post_init__(self):
        self.allowed_users = frozenset(int(u) for u in self.allowed_users)

    def _new_card(self, alert_id: str, kind: str, text: str) -> Card:
        buttons = [(BUTTON_LABELS[d], callback_data(d, alert_id))
                   for d in DECISIONS_FOR_KIND[kind]]
        card = Card(alert_id, kind, text, buttons)
        self.cards[alert_id] = card
        while len(self.cards) > MAX_CARDS:
            self.cards.popitem(last=False)
        return card

    def _close_open(self, line_for_kind) -> List[Close]:
        closes = []
        for card in self.cards.values():
            if card.open:
                card.open = False
                closes.append(Close(card, card.text + "\n\n" + line_for_kind[card.kind]))
        return closes

    def new_alert(self, alert_id: str, clock: str) -> Tuple[List[Close], Optional[Card]]:
        """State machine sent /telegram/alert. Repeated ids are ignored."""
        if alert_id in self.cards:
            return [], None
        closes = self._close_open({ALERT: SUPERSEDED_LINE, BLOCKING: SUPERSEDED_LINE})
        return closes, self._new_card(alert_id, ALERT, alert_text(alert_id, clock))

    def new_blocking(self, alert_id: str, clock: str) -> Tuple[List[Close], Optional[Card]]:
        """State machine sent /telegram/blocking (after Deny or the 30 s timeout)."""
        if alert_id in self.cards:
            return [], None
        closes = self._close_open({ALERT: EXPIRED_LINE, BLOCKING: SUPERSEDED_LINE})
        return closes, self._new_card(alert_id, BLOCKING, blocking_text(alert_id, clock))

    def press(self, data: str, user_id: int, user_name: str) -> PressResult:
        """Someone pressed a button in the chat."""
        parsed = parse_callback(data)
        if parsed is None:
            return PressResult("Unknown button")
        if self.allowed_users and int(user_id) not in self.allowed_users:
            return PressResult("You are not allowed to answer alerts")
        decision, alert_id = parsed
        card = self.cards.get(alert_id)
        if card is None or not card.open:
            return PressResult("This alert is no longer active")
        if decision not in DECISIONS_FOR_KIND[card.kind]:
            return PressResult("Unknown button")
        card.open = False
        line = RESULT_LINES[decision] % user_name
        return PressResult(
            toast=line,
            decision={"id": alert_id, "decision": decision},
            close=Close(card, card.text + "\n\n" + line),
        )
