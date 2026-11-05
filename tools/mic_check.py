"""Mic check for the spoken password: where do the failures come from?

Each try plays "Say the password" and the "three, two, one" countdown, then
records a fixed window from the moment the countdown ends (no speech
threshold, so it can't hide anything). The clip goes to the operator chat on
Telegram with what Vosk heard, the levels and the timing:

  - free / grammar: Vosk with no word list, and with only digits + vosk words
  - match: would the password node accept it (ROBOT_PASSWORD_HASH)
  - peak, RMS, clipped %, noise floor; would it pass energy_threshold
  - gap: countdown end -> first recorded sample; speech start in the window

Run inside the robot's container with password_node stopped (only one
program can open the mic):

  python3 tools/mic_check.py --env-file .env                 # 3 tries at the current gain
  python3 tools/mic_check.py --env-file .env --gain 40,60,80,100 --tries 2
"""

import argparse
import asyncio
import json
import math
import os
import subprocess
import sys
import time
from array import array

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for pkg in ("password_system", "telegram_alert", "audio_player"):
    sys.path.insert(0, os.path.join(ROOT, "src", pkg))

from password_system.speech import vosk_candidates, vosk_grammar  # noqa: E402
from password_system.verifier import PasswordVerifier, parse_stored  # noqa: E402

RATE = 44100  # the USB mic's own rate, as password_node opens it
CHUNK = 1024  # SpeechRecognition's chunk size, for the energy check
CLIPPED = 32700


def play(clip, card):
    path = os.path.join(ROOT, "src", "audio_player", "clips", clip + ".wav")
    subprocess.run(["aplay", "-q", "-D", "plughw:%d,0" % card, path], check=True)


def set_gain(card, percent):
    subprocess.run(["amixer", "-q", "-c", str(card), "sset", "Mic", "capture",
                    "%d%%" % percent], check=True)


def get_gain(card):
    out = subprocess.run(["amixer", "-c", str(card), "sget", "Mic"],
                         capture_output=True, text=True).stdout
    for part in out.split("Capture")[1:]:
        if "[" in part and "%]" in part:
            return int(part.split("[", 1)[1].split("%", 1)[0])
    return None


def db(value):
    return 20 * math.log10(max(value, 1) / 32768.0)


def levels(raw, threshold):
    """Peak, RMS, clipped %, noise floor (first 0.3 s) and when the speech
    energy first passes the threshold (SpeechRecognition's chunk RMS)."""
    samples = array("h", raw)
    n = len(samples) or 1
    peak = max((abs(s) for s in samples), default=0)
    rms = math.sqrt(sum(s * s for s in samples) / n)
    clipped = 100.0 * sum(1 for s in samples if abs(s) >= CLIPPED) / n
    noise_n = int(RATE * 0.3)
    noise = math.sqrt(sum(s * s for s in samples[:noise_n]) / max(noise_n, 1))
    loudest, start = 0.0, None
    for i in range(0, len(samples), CHUNK):
        chunk = samples[i:i + CHUNK]
        energy = math.sqrt(sum(s * s for s in chunk) / max(len(chunk), 1))
        loudest = max(loudest, energy)
        if start is None and energy > threshold:
            start = i / RATE
    return {"peak_db": db(peak), "rms_db": db(rms), "clipped_pct": clipped,
            "noise": noise, "loudest": loudest, "speech_at": start}


def transcribe(model, pcm16k, grammar):
    from vosk import KaldiRecognizer
    rec = KaldiRecognizer(model, 16000, *((grammar,) if grammar else ()))
    rec.SetMaxAlternatives(3)
    rec.AcceptWaveform(pcm16k)
    found = vosk_candidates(rec.FinalResult())
    return found[0] if found else ""


def record(pa, device, seconds):
    """Open the mic and record; returns (raw 44.1 kHz bytes, open time in s)."""
    import pyaudio
    t0 = time.monotonic()
    stream = pa.open(format=pyaudio.paInt16, channels=1, rate=RATE, input=True,
                     input_device_index=device, frames_per_buffer=CHUNK)
    opened = time.monotonic() - t0
    frames = [stream.read(CHUNK, exception_on_overflow=False)
              for _ in range(int(RATE * seconds / CHUNK))]
    stream.stop_stream()
    stream.close()
    return b"".join(frames), opened


def caption(n, gain, gap, lv, free, grammar_heard, match, threshold):
    yes = lambda b: "yes" if b else "NO"
    speech = ("%.2f s into the window" % lv["speech_at"]) if lv["speech_at"] is not None \
        else "never above %d" % threshold
    return "\n".join([
        "🎙 Mic check %d (gain %s%%)" % (n, gain if gain is not None else "?"),
        'free speech: "%s"' % (free or "-"),
        'grammar: "%s"' % (grammar_heard or "-"),
        "password match: %s" % yes(match),
        "peak %.1f dBFS, RMS %.1f dBFS, clipped %.2f%%" % (
            lv["peak_db"], lv["rms_db"], lv["clipped_pct"]),
        "noise %d, loudest %d, threshold %d: %s" % (
            lv["noise"], lv["loudest"], threshold, yes(lv["loudest"] > threshold)),
        "speech starts %s" % speech,
        "gap countdown end -> recording: %d ms" % (gap * 1000),
    ])


async def send(settings, data, kind, text):
    from telegram import Bot
    async with Bot(settings.token) as bot:
        if kind == "voice":
            await bot.send_voice(chat_id=settings.chat_id, voice=data, caption=text)
        else:
            await bot.send_document(chat_id=settings.chat_id, document=data,
                                    filename="mic_check.wav", caption=text)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tries", type=int, default=3, help="tries per gain")
    ap.add_argument("--gain", default="", help="mic capture %% to try, e.g. 40,60,80,100")
    ap.add_argument("--seconds", type=float, default=5.0, help="recording window")
    ap.add_argument("--card", type=int, default=2, help="ALSA card (USB audio)")
    ap.add_argument("--device", type=int, default=0, help="PyAudio input device")
    ap.add_argument("--threshold", type=float, default=4000.0,
                    help="password_node's energy_threshold to compare against")
    ap.add_argument("--model", default="/root/share/vosk-model-small-en-us-0.15")
    ap.add_argument("--words", default="hello", help="extra grammar words (vosk_words)")
    ap.add_argument("--env-file", default=os.path.join(ROOT, ".env"))
    ap.add_argument("--no-telegram", action="store_true")
    args = ap.parse_args()

    import pyaudio
    import speech_recognition as sr
    from vosk import Model, SetLogLevel
    from telegram_alert.settings import load_settings
    from telegram_alert.voice import to_voice

    SetLogLevel(-1)
    model = Model(args.model)
    grammar = vosk_grammar(args.words)
    stored = os.environ.get("ROBOT_PASSWORD_HASH", "")
    verifier = PasswordVerifier(*parse_stored(stored)) if stored else None
    settings = None if args.no_telegram else load_settings(env_file=args.env_file)

    original_gain = get_gain(args.card)
    gains = [int(g) for g in args.gain.split(",") if g.strip()] or [None]
    pa = pyaudio.PyAudio()
    n = 0
    try:
        for gain in gains:
            if gain is not None:
                set_gain(args.card, gain)
            for _ in range(args.tries):
                n += 1
                print("try %d: prompt and countdown..." % n, flush=True)
                play("password_prompt", args.card)
                play("password_countdown", args.card)
                raw, opened = record(pa, args.device, args.seconds)
                gap = opened  # countdown end -> mic stream open and recording
                audio = sr.AudioData(raw, RATE, 2)
                pcm16k = audio.get_raw_data(convert_rate=16000, convert_width=2)
                lv = levels(raw, args.threshold)
                free = transcribe(model, pcm16k, None)
                heard = transcribe(model, pcm16k, grammar)
                match = bool(verifier) and any(verifier.matches(t) for t in (free, heard) if t)
                text = caption(n, gain if gain is not None else get_gain(args.card),
                               gap, lv, free, heard, match, args.threshold)
                print(text + "\n", flush=True)
                if settings is not None:
                    kind, data = to_voice(audio.get_wav_data(convert_rate=16000, convert_width=2))
                    asyncio.run(send(settings, data, kind, text))
                time.sleep(1.0)
    finally:
        pa.terminate()
        if original_gain is not None:
            set_gain(args.card, original_gain)


if __name__ == "__main__":
    main()
