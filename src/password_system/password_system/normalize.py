"""Normalize transcribed speech so small transcription differences still match.

Speech engines write the same words in different ways: "1352", "1 3 5 2",
"one three five two", "1,352". Both the stored password and every
transcription go through ``normalize`` before comparing, so all of these
become "1352". Rules:

- lower case, Unicode NFC
- English digit words (and common homophones like "to", "for") -> digits
- Thai digits (๑๒๓) and Thai digit words (หนึ่ง สอง สาม) -> digits
- drop spaces and punctuation; keep letters, digits and Thai vowel/tone marks
"""

import re
import unicodedata

THAI_DIGITS = str.maketrans("๐๑๒๓๔๕๖๗๘๙", "0123456789")

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

# Thai has no spaces between words, so these are plain substring replaces.
THAI_NUMBER_WORDS = (
    ("ศูนย์", "0"), ("หนึ่ง", "1"), ("สอง", "2"), ("สาม", "3"), ("สี่", "4"),
    ("ห้า", "5"), ("หก", "6"), ("เจ็ด", "7"), ("แปด", "8"), ("เก้า", "9"),
)


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFC", text).lower().translate(THAI_DIGITS)
    text = _ENGLISH_RE.sub(lambda m: ENGLISH_NUMBER_WORDS[m.group(1)], text)
    for word, digit in THAI_NUMBER_WORDS:
        text = text.replace(word, digit)
    # L = letters, M = combining marks (Thai vowels / tones), N = numbers
    return "".join(c for c in text if unicodedata.category(c)[0] in "LMN")
