"""Keyboard input instead of the camera (input_mode: keyboard), so Lane 1 and
Lane 5 can drive words from a terminal without a webcam or MediaPipe.

    w forward   s back   a left   d right   space stop   x none

With ``hold_s > 0`` a word lasts ``hold_s`` after the last key press, then
falls back to ``none`` (hold a key down: terminal key repeat keeps it
alive). With ``hold_s <= 0`` a word stays until another key is pressed.

Keys match exactly (lowercase only). Arrow and function keys send escape
sequences whose last byte can be an uppercase letter (up arrow is ESC [ A),
so ``KeyFilter`` drops those sequences and uppercase is never mapped.

``KeyboardCommand`` and ``KeyFilter`` are plain Python. ``read_keys`` needs a
real terminal and imports termios / msvcrt inside the function.
"""

import os
import sys
import threading
from typing import Callable, Optional

KEYMAP = {"w": "forward", "s": "back", "a": "left", "d": "right", " ": "stop", "x": "none"}
HELP = "keys: w forward, s back, a left, d right, space stop, x none"


class KeyboardCommand:
    def __init__(self, hold_s: float = 0.8):
        self.hold_s = hold_s
        self._lock = threading.Lock()
        self._word = "none"
        self._stamp: Optional[float] = None

    def press(self, key: str, now: float) -> Optional[str]:
        """Handle one key. Returns the new word, or None for an unmapped key."""
        word = KEYMAP.get(key) if key else None
        if word is None:
            return None
        with self._lock:
            self._word, self._stamp = word, now
        return word

    def force_none(self, now: float) -> None:
        """Input is gone (reader thread died, stdin closed): publish none."""
        with self._lock:
            self._word, self._stamp = "none", now

    def word(self, now: float) -> str:
        with self._lock:
            if self._stamp is None:
                return "none"
            if self.hold_s > 0 and now - self._stamp > self.hold_s:
                return "none"
            return self._word


class KeyFilter:
    """Drops the bytes of terminal escape sequences, one char at a time.

    POSIX: ESC [ ... final (final byte in '@'..'~'), ESC O x, ESC x.
    Windows (msvcrt): NUL or 0xE0 followed by one scan code char.
    ``feed`` returns the char if it is a plain key, else None.
    """

    def __init__(self):
        self._state = None  # None | "esc" | "csi" | "one"

    def feed(self, ch: str) -> Optional[str]:
        st = self._state
        if st == "esc":
            self._state = "csi" if ch == "[" else ("one" if ch == "O" else None)
            return None
        if st == "csi":
            if "@" <= ch <= "~":
                self._state = None
            return None
        if st == "one":
            self._state = None
            return None
        if ch == "\x1b":
            self._state = "esc"
            return None
        if ch in ("\x00", "\xe0"):
            self._state = "one"
            return None
        return ch


def read_keys(on_key: Callable[[str], None], stop: threading.Event) -> None:
    """Call ``on_key`` for every plain key typed in this terminal until
    ``stop``. Escape sequences (arrows, function keys) are dropped.
    Raises RuntimeError if stdin is not a terminal (e.g. under ros2 launch)
    and EOFError if stdin closes."""
    filt = KeyFilter()
    if os.name == "nt":
        import msvcrt
        import time

        while not stop.is_set():
            if msvcrt.kbhit():
                ch = filt.feed(msvcrt.getwch())
                if ch:
                    on_key(ch)
            else:
                time.sleep(0.02)
        return

    if not sys.stdin.isatty():
        raise RuntimeError("keyboard mode needs a terminal: use `ros2 run`, not `ros2 launch`")
    import select
    import termios
    import tty

    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setcbreak(fd)  # keys arrive one by one, Ctrl+C still works
        while not stop.is_set():
            ready, _, _ = select.select([fd], [], [], 0.1)
            if ready:
                data = os.read(fd, 1)
                if not data:
                    raise EOFError("stdin closed")
                ch = filt.feed(data.decode(errors="ignore"))
                if ch:
                    on_key(ch)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)
