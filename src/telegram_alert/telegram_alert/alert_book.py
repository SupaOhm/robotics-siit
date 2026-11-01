"""Telegram alert bookkeeping (no ROS, no Telegram library).

Decides which Telegram messages ("cards") to send, which to close, and what a
button press means. ``bot.py`` does the actual Telegram calls.

Contract (docs/interfaces.md v0.3, D11, D14, D15, D30):
- /telegram/alert <id>     -> card with a photo and Allow / Deny buttons
- /telegram/blocking <id>  -> card "Robot is blocking" with a Resume button.
  It also closes any Allow / Deny card nobody answered: the 30 s timeout
  lives in the state machine, which treats it as Deny.
- a button press           -> {"id": ..., "decision": "allow"|"deny"|"resume"}
  on /telegram/decision, and the card's buttons are removed.
- /robot/state leaving WAIT_OPERATOR or BLOCKING (e.g. the operator held
  `back`) closes the cards that state was waiting on.

Every card's buttons carry a token that is unique to this run, so a button
on an old card can never act on a newer alert, even if alert ids repeat
after the state machine restarts.
"""

import secrets
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Iterable, List, Optional, Tuple

ALLOW, DENY, RESUME = "allow", "deny", "resume"
ALERT, BLOCKING = "alert", "blocking"
DECISIONS_FOR_KIND = {ALERT: (ALLOW, DENY), BLOCKING: (RESUME,)}
BUTTON_LABELS = {ALLOW: "✅ Allow", DENY: "⛔ Deny", RESUME: "▶️ Resume"}
RESULT_LINES = {ALLOW: "✅ Allowed by %s", DENY: "⛔ Denied by %s",
                RESUME: "▶️ Resumed by %s"}

# State machine states (docs/interfaces.md) whose cards are waiting for a press
STATE_FOR_KIND = {ALERT: "WAIT_OPERATOR", BLOCKING: "BLOCKING"}

EXPIRED_LINE = "⌛ No answer in %d s: treated as Deny"
SUPERSEDED_LINE = "Closed: a newer alert replaced this one"
MOVED_ON_LINE = "Closed: the robot moved on (now %s)"

MAX_CALLBACK_BYTES = 64  # Telegram limit for callback_data
MAX_CARDS = 50


def callback_data(decision: str, alert_id: str, token: str) -> str:
    data = "%s:%s:%s" % (decision, token, alert_id)
    if len(data.encode("utf-8")) > MAX_CALLBACK_BYTES:
        raise ValueError("alert id too long for a Telegram button: %r" % alert_id)
    return data


def parse_callback(data: str) -> Optional[Tuple[str, str, str]]:
    """'allow:k1:a3' -> ('allow', 'a3', 'k1'); None if it isn't one of our buttons."""
    parts = (data or "").split(":", 2)
    if len(parts) != 3 or parts[0] not in BUTTON_LABELS or not parts[1] or not parts[2]:
        return None
    decision, token, alert_id = parts
    return decision, alert_id, token


def alert_text(alert_id: str, clock: str, timeout_s: int) -> str:
    # Not "wrong password 3 times": WAIT_OPERATOR also follows a password
    # check with no result in 60 s (D30).
    return ("🚨 Checkpoint: this person did not pass the password check.\n"
            "Alert %s at %s\n"
            "Allow this person to pass? No answer in %d s = Deny."
            % (alert_id, clock, timeout_s))


def blocking_text(alert_id: str, clock: str) -> str:
    return ("🛑 Robot is blocking the person.\n"
            "Alert %s at %s\n"
            "Press Resume to let the robot turn away and continue." % (alert_id, clock))


@dataclass
class Card:
    """One Telegram message with buttons."""
    alert_id: str
    kind: str                       # ALERT | BLOCKING
    token: str
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
    timeout_s: int = 30  # the state machine's WAIT_OPERATOR timeout, for the text only
    cards: "OrderedDict[str, Card]" = field(default_factory=OrderedDict)  # by token

    def __post_init__(self):
        self.allowed_users = frozenset(int(u) for u in self.allowed_users)
        self._run = secrets.token_hex(2)  # differs after a node restart
        self._serial = 0

    def _new_card(self, alert_id: str, kind: str, text: str) -> Card:
        self._serial += 1
        token = "%s%d" % (self._run, self._serial)
        buttons = [(BUTTON_LABELS[d], callback_data(d, alert_id, token))
                   for d in DECISIONS_FOR_KIND[kind]]
        card = Card(alert_id, kind, token, text, buttons)
        self.cards[token] = card
        while len(self.cards) > MAX_CARDS:
            self.cards.popitem(last=False)
        return card

    def _is_open_duplicate(self, alert_id: str, kind: str) -> bool:
        return any(c.open and c.alert_id == alert_id and c.kind == kind
                   for c in self.cards.values())

    def _close_open(self, line_for_kind, kinds=(ALERT, BLOCKING)) -> List[Close]:
        closes = []
        for card in self.cards.values():
            if card.open and card.kind in kinds:
                card.open = False
                closes.append(Close(card, card.text + "\n\n" + line_for_kind[card.kind]))
        return closes

    def new_alert(self, alert_id: str, clock: str) -> Tuple[List[Close], Optional[Card]]:
        """State machine sent /telegram/alert. An id that is still open is a
        duplicate and ignored; a reused id (state machine restarted) is new."""
        if self._is_open_duplicate(alert_id, ALERT):
            return [], None
        closes = self._close_open({ALERT: SUPERSEDED_LINE, BLOCKING: SUPERSEDED_LINE})
        text = alert_text(alert_id, clock, self.timeout_s)
        return closes, self._new_card(alert_id, ALERT, text)

    def new_blocking(self, alert_id: str, clock: str) -> Tuple[List[Close], Optional[Card]]:
        """State machine sent /telegram/blocking (after Deny or the 30 s timeout)."""
        if self._is_open_duplicate(alert_id, BLOCKING):
            return [], None
        expired = EXPIRED_LINE % self.timeout_s
        closes = self._close_open({ALERT: expired, BLOCKING: SUPERSEDED_LINE})
        return closes, self._new_card(alert_id, BLOCKING, blocking_text(alert_id, clock))

    def state_changed(self, old: str, new: str) -> List[Close]:
        """/robot/state went from ``old`` to ``new``. Leaving WAIT_OPERATOR or
        BLOCKING closes that state's open cards, so a stale button can't look
        live. WAIT_OPERATOR -> BLOCKING is left to /telegram/blocking, which
        marks the alert as expired."""
        line = MOVED_ON_LINE % new
        kinds = [kind for kind, state in STATE_FOR_KIND.items()
                 if old == state and new != state
                 and not (kind == ALERT and new == STATE_FOR_KIND[BLOCKING])]
        return self._close_open({ALERT: line, BLOCKING: line}, kinds)

    def press(self, data: str, user_id: int, user_name: str) -> PressResult:
        """Someone pressed a button in the chat."""
        parsed = parse_callback(data)
        if parsed is None:
            return PressResult("Unknown button")
        if self.allowed_users and int(user_id) not in self.allowed_users:
            return PressResult("You are not allowed to answer alerts")
        decision, alert_id, token = parsed
        card = self.cards.get(token)
        if card is None or not card.open or card.alert_id != alert_id:
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
