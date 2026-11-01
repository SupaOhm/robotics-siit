"""Normalize transcribed speech so small transcription differences still match.

Speech engines write the same digits in different ways: "1352", "1 3 5 2",
"one three five two", "1,352". Both the stored password and every
transcription go through ``normalize`` before comparing, so all of these
become "1352". Rules:

- lower case, Unicode NFC
- English digit words (and common homophones like "to", "for") -> digits
- drop spaces and punctuation; keep letters and digits
"""

import re
import unicodedata

ENGLISH_NUMBER_WORDS = {
    "zero": "0", "oh": "0",
    "one": "1",
    "two": "2", "to": "2", "too": "2",
    "three": "3",
    "four": "4", "for": "4",
    "five": "5",
    "six": "6",
    "seven": "7",
    "eight": "8",
    "nine": "9",
}
_ENGLISH_RE = re.compile(r"\b(%s)\b" % "|".join(ENGLISH_NUMBER_WORDS))


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFC", text).lower()
    text = _ENGLISH_RE.sub(lambda m: ENGLISH_NUMBER_WORDS[m.group(1)], text)
    return "".join(c for c in text if c.isalnum())
