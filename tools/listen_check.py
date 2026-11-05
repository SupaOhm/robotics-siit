"""Robot check of the real listen_once (D34), not a copy of its logic.

mic_check.py has its own Logic 2, so it can't show that password_node's
listening works. This calls SpeechListener.listen_once with password_node's
settings, 10 tries of each:

  normal  Say the password as usual                 must be 10/10
  paused  Say it with a 1 s pause between digits    no pass mark: it shows
                                                    whether "first phrase is
                                                    the answer" (D34) holds
  digits  "Say zero" ... "Say nine" (tools/clips/)  must be at least 9/10
  silent  Beep only, nobody speaks                  must all be no_speech

This counts tries, so unlike a real session it asks again after a right
answer, once the robot has said "Password correct". In a real session
`granted` ends it and the state machine goes to PASS.

Stop password_node first (it keeps the mic open), then in the container:

  amixer -c 2 sset Mic capture 40%
  python3 -W ignore tools/listen_check.py
  python3 -W ignore tools/listen_check.py --sections silent --tries 5

The password comes from ROBOT_PASSWORD_HASH. What was heard in normal and
paused is never printed, so the output can go on a public PR.
"""

import argparse
import os
import sys

from mic_check import ROOT, first_digit, play

from password_system.speech import DIGIT_WORDS, SpeechListener
from password_system.verifier import PasswordVerifier, parse_stored

SECTIONS = ("normal", "paused", "digits", "silent")
DIGITS = [w for w in DIGIT_WORDS if w != "oh"]
PASS_MARK = {"normal": 1.0, "digits": 0.9, "silent": 1.0}  # paused: report only


def listen(listener, card, prompt="password_prompt"):
    """One try, as password_node runs it: prompt, countdown, beep, listen."""
    play(prompt, card)
    play("password_countdown", card)
    play("password_beep", card)
    return listener.listen_once()


def password_try(listener, verifier, card):
    result = listen(listener, card)
    ok = any(verifier.matches(c) for c in result.candidates)
    # As a real session replies: state_machine's PASS, password_node's retry
    play("password_correct" if ok else "password_wrong", card)
    return ok, "%s %s" % (result.kind, "✅" if ok else "❌")


def digit_try(listener, word, card):
    clip = os.path.join(ROOT, "tools", "clips", "say_%s.wav" % word)
    result = listen(listener, card, clip)
    heard = first_digit(result.candidates[0]) if result.candidates else ""
    ok = heard == first_digit(word)
    return ok, "%s → %s %s" % (word, heard or result.kind, "✅" if ok else "❌")


def silent_try(listener, card):
    play("password_beep", card)  # no "Say the password": nobody should answer
    result = listener.listen_once()
    ok = result.kind == "no_speech"
    what = "with a word" if result.candidates else "no word"
    return ok, "no_speech ✅" if ok else "%s, %s ❌" % (result.kind, what)


def run_section(section, tries, listener, verifier, card):
    if section == "digits":
        asks = [DIGITS[i % len(DIGITS)] for i in range(tries)]
    else:
        asks = [None] * tries
    right = 0
    print("\n== %s ==" % section, flush=True)
    if section == "paused":
        print("Say the password with a 1 s pause between the digits.", flush=True)
    elif section == "silent":
        print("Nobody speaks.", flush=True)
    for n, word in enumerate(asks, 1):
        if section == "digits":
            ok, line = digit_try(listener, word, card)
        elif section == "silent":
            ok, line = silent_try(listener, card)
        else:
            ok, line = password_try(listener, verifier, card)
        right += ok
        print("%2d: %s" % (n, line), flush=True)
    return right


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sections", default=",".join(SECTIONS))
    ap.add_argument("--tries", type=int, default=10, help="tries per section")
    ap.add_argument("--card", type=int, default=2, help="ALSA card (speaker)")
    ap.add_argument("--device", type=int, default=0, help="PyAudio input device")
    ap.add_argument("--rate", type=int, default=48000, help="mic_sample_rate")
    ap.add_argument("--model", default="/root/share/vosk-model-small-en-us-0.15")
    ap.add_argument("--words", default="", help="vosk_words")
    ap.add_argument("--match", default="first", help="match_mode, as in password.yaml")
    args = ap.parse_args()
    sections = [s for s in args.sections.split(",") if s]

    verifier = None
    if {"normal", "paused"} & set(sections):
        stored = os.environ.get("ROBOT_PASSWORD_HASH", "")
        if not stored:
            sys.exit("ROBOT_PASSWORD_HASH is not set")
        verifier = PasswordVerifier(*parse_stored(stored), match_mode=args.match)

    listener = SpeechListener(engine="vosk", device_index=args.device, sample_rate=args.rate,
                              vosk_model_path=args.model, vosk_words=args.words)
    listener.open_mic()
    scores = {}
    try:
        for section in sections:
            scores[section] = run_section(section, args.tries, listener, verifier, args.card)
    finally:
        listener.close_mic()

    print("\n📊 listen_once (D34)")
    passed = True
    for section, right in scores.items():
        mark = PASS_MARK.get(section)
        verdict = "report only"
        if mark is not None:
            ok = right >= mark * args.tries
            passed = passed and ok
            verdict = "✅" if ok else "❌"
        print("%-7s %d/%d %s" % (section, right, args.tries, verdict))
    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()
