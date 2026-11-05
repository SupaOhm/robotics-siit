"""Mic check for the spoken password: where do the failures come from?

Each try plays "Say the password", the "three, two, one" countdown and a
beep, then listens up to 10 s from the moment the beep ends. The same audio goes
through two listening logics at once, so they can be compared:

  Logic 1, threshold listen (password_node today, SpeechRecognition's
    listen()): speech starts when a chunk is louder than energy_threshold,
    keeps 0.5 s from before, ends after 0.8 s of quiet or 5 s; no speech in
    6 s = silence. The phrase is then transcribed.
  Logic 2, Vosk streaming (proposed): every chunk goes straight to Vosk;
    the first phrase it recognises as words is the answer. No threshold.

Each logic is run with Vosk free speech (no word list) and with the grammar
(digits + --words). The clip goes to Telegram with what each heard, whether
it matches ROBOT_PASSWORD_HASH, the levels and the timing.

The mic is opened once and read continuously, so nothing re-opens it
between tries (re-opening hung on the robot). Run inside the container with
password_node stopped (only one program can open the mic):

  python3 tools/mic_check.py --env-file .env                 # 3 tries at the current gain
  python3 tools/mic_check.py --env-file .env --gain 40,60,80,100 --tries 2
  python3 tools/mic_check.py --env-file .env --digits        # "Say zero" ... "Say nine"

--digits asks for each digit in turn (clips in tools/clips/), checks with
the digits-only word list as password_node does, and ends with a summary
table on Telegram: which digits this voice and accent are heard right.
"""

import argparse
import asyncio
import audioop
import math
import os
import queue
import subprocess
import sys
import threading
import time
from array import array

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for pkg in ("password_system", "telegram_alert", "audio_player"):
    sys.path.insert(0, os.path.join(ROOT, "src", pkg))

from password_system.normalize import normalize  # noqa: E402
from password_system.speech import DIGIT_WORDS, vosk_candidates, vosk_grammar  # noqa: E402
from password_system.verifier import PasswordVerifier, parse_stored  # noqa: E402

RATE = 48000   # the USB mic at 44100 really delivers ~24,300 samples/s (1.8x fast)
CHUNK = 1024   # SpeechRecognition's chunk size
CHUNK_S = CHUNK / RATE
CLIPPED = 32700
WINDOW = 10.0  # s of listening after the countdown
# password_node's listen settings (password.yaml)
ONSET_TIMEOUT, PAUSE, PRE_ROLL, PHRASE_LIMIT = 6.0, 0.8, 0.5, 5.0


def play(clip, card):
    path = clip if clip.endswith(".wav") else os.path.join(
        ROOT, "src", "audio_player", "clips", clip + ".wav")
    subprocess.run(["aplay", "-q", "-D", "plughw:%d,0" % card, path], check=True, timeout=15)


def set_gain(card, percent):
    subprocess.run(["amixer", "-q", "-c", str(card), "sset", "Mic", "capture",
                    "%d%%" % percent], check=True, timeout=5)


def get_gain(card):
    """Capture % of the Mic control ("... Capture 21 [60%] ...")."""
    out = subprocess.run(["amixer", "-c", str(card), "sget", "Mic"],
                         capture_output=True, text=True, timeout=5).stdout
    for line in out.splitlines():
        if "Capture" in line and "%]" in line:
            tail = line.split("Capture", 1)[1]
            return int(tail.split("[", 1)[1].split("%", 1)[0])
    return None


def rms(raw):
    return audioop.rms(raw, 2) if raw else 0


def db(value):
    return 20 * math.log10(max(value, 1) / 32768.0)


class Mic:
    """The mic, opened once; a thread reads it into a queue."""

    def __init__(self, device):
        import pyaudio
        self.pa = pyaudio.PyAudio()
        self.stream = self.pa.open(format=pyaudio.paInt16, channels=1, rate=RATE, input=True,
                                   input_device_index=device, frames_per_buffer=CHUNK)
        self.chunks = queue.Queue()
        self.running = True
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self):
        while self.running:
            self.chunks.put((time.monotonic(), self.stream.read(CHUNK, exception_on_overflow=False)))

    def flush(self):
        """Drop what was heard so far (the robot's own prompt)."""
        while not self.chunks.empty():
            self.chunks.get_nowait()

    def next(self):
        return self.chunks.get(timeout=2.0)  # raises queue.Empty if the mic stalls

    def close(self):
        self.running = False
        time.sleep(0.1)
        self.stream.close()
        self.pa.terminate()


class ThresholdListen:
    """Logic 1: SpeechRecognition's listen(), on the same chunks."""

    def __init__(self, threshold):
        self.threshold = threshold
        self.before = []          # pre-roll chunks
        self.phrase = []
        self.start = self.end = None
        self.quiet = 0.0
        self.done = False
        self.result = "no speech"

    def feed(self, t, raw):
        if self.done:
            return
        if self.start is None:
            self.before = (self.before + [raw])[-int(PRE_ROLL / CHUNK_S):]
            if rms(raw) > self.threshold:
                self.start, self.phrase = t, list(self.before)
            elif t >= ONSET_TIMEOUT:
                self.done = True  # silence
            return
        self.phrase.append(raw)
        self.quiet = self.quiet + CHUNK_S if rms(raw) <= self.threshold else 0.0
        if self.quiet >= PAUSE or t - self.start >= PHRASE_LIMIT:
            self.end, self.done, self.result = t, True, "speech"


class VoskStream:
    """Logic 2: every chunk straight to Vosk; first recognised phrase wins."""

    def __init__(self, model, grammar):
        from vosk import KaldiRecognizer
        self.rec = KaldiRecognizer(model, 16000, *((grammar,) if grammar else ()))
        self.rec.SetMaxAlternatives(3)
        self.heard, self.at, self.done = "", None, False

    def feed(self, t, pcm16k):
        if self.done:
            return
        if self.rec.AcceptWaveform(pcm16k):
            found = vosk_candidates(self.rec.Result())
            if found:
                self.heard, self.at, self.done = found[0], t, True

    def finish(self, t):
        if not self.done:
            found = vosk_candidates(self.rec.FinalResult())
            self.heard, self.at, self.done = (found[0] if found else ""), t, True


def transcribe(model, pcm16k, grammar):
    from vosk import KaldiRecognizer
    rec = KaldiRecognizer(model, 16000, *((grammar,) if grammar else ()))
    rec.SetMaxAlternatives(3)
    rec.AcceptWaveform(pcm16k)
    found = vosk_candidates(rec.FinalResult())
    return found[0] if found else ""


def to16k(raw):
    return audioop.ratecv(raw, 2, 1, RATE, 16000, None)[0]


def one_try(mic, model, grammar, threshold, card, prompt="password_prompt"):
    play(prompt, card)
    play("password_countdown", card)
    play("password_beep", card)  # "speak now": the mic opens as it ends, like password_node
    ended = time.monotonic()  # aplay returns once the clip has played
    mic.flush()
    logic1 = ThresholdListen(threshold)
    free2, gram2 = VoskStream(model, None), VoskStream(model, grammar)
    state, raw_all, first = None, [], None
    while True:
        at, raw = mic.next()
        if at < ended:
            continue  # recorded while the countdown was still playing
        first = first if first is not None else at - CHUNK_S
        t = at - first
        raw_all.append(raw)
        pcm, state = audioop.ratecv(raw, 2, 1, RATE, 16000, state)
        logic1.feed(t, raw)
        free2.feed(t, pcm)
        gram2.feed(t, pcm)
        if t >= WINDOW or (logic1.done and free2.done and gram2.done):
            break
    free2.finish(t)
    gram2.finish(t)
    logic1_text = {}
    if logic1.result == "speech":
        seg = to16k(b"".join(logic1.phrase))
        logic1_text = {"free": transcribe(model, seg, None), "grammar": transcribe(model, seg, grammar)}
    return {"gap": max(first - ended, 0.0), "raw": b"".join(raw_all), "logic1": logic1,
            "logic1_text": logic1_text, "free2": free2, "gram2": gram2}


def levels(raw, threshold):
    samples = array("h", raw)
    n = len(samples) or 1
    peak = max((abs(s) for s in samples), default=0)
    clipped = 100.0 * sum(1 for s in samples if abs(s) >= CLIPPED) / n
    loudest = max((rms(raw[i:i + 2 * CHUNK]) for i in range(0, len(raw), 2 * CHUNK)), default=0)
    return {"peak_db": db(peak), "rms_db": db(rms(raw)), "clipped": clipped,
            "noise": rms(raw[:2 * int(RATE * 0.3)]), "loudest": loudest}


def caption(n, gain, r, verifier, threshold):
    # No password to compare in --digits mode: the asked digit is the answer
    ok = lambda text: "" if verifier is None else (
        "✅" if text and verifier.matches(text) else "❌")
    q = lambda text: '"%s"' % text if text else "nothing"
    l1, t1 = r["logic1"], r["logic1_text"]
    if l1.result == "speech":
        logic1 = ["Logic 1 · threshold listen (password_node now)",
                  "  speech %.2f–%.2f s" % (l1.start, l1.end),
                  "  free %s %s · grammar %s %s" % (q(t1["free"]), ok(t1["free"]),
                                                    q(t1["grammar"]), ok(t1["grammar"]))]
    else:
        logic1 = ["Logic 1 · threshold listen (password_node now)",
                  "  ❌ no speech above %d in %.0f s (counts as silence)" % (threshold, ONSET_TIMEOUT)]
    f2, g2 = r["free2"], r["gram2"]
    lv = levels(r["raw"], threshold)
    return "\n".join(["🎙 Mic check %d (gain %s%%)" % (n, gain)] + logic1 + [
        "Logic 2 · Vosk streaming (proposed)",
        "  free %s %s at %.2f s · grammar %s %s at %.2f s" % (
            q(f2.heard), ok(f2.heard), f2.at, q(g2.heard), ok(g2.heard), g2.at),
        "Levels: peak %.1f dBFS, RMS %.1f dBFS, clipped %.2f%%, noise %d, loudest %d" % (
            lv["peak_db"], lv["rms_db"], lv["clipped"], lv["noise"], lv["loudest"]),
        "Gap countdown end → listening: %d ms" % (r["gap"] * 1000),
    ])


def first_digit(text):
    digits = [c for c in normalize(text or "") if c.isdigit()]
    return digits[0] if digits else ""


def digit_row(word, r, model):
    """Asked digit vs the first digit heard, as password_node's check does
    (Logic 1, digits-only word list), plus Logic 2 and free speech."""
    want = normalize(word)
    l1 = r["logic1_text"].get("grammar", "") if r["logic1"].result == "speech" else ""
    l2 = r["gram2"].heard
    heard = first_digit(l1) or "-"
    free = r["logic1_text"].get("free", "") or r["free2"].heard
    return {"word": word, "want": want, "heard": heard, "ok1": first_digit(l1) == want,
            "ok2": first_digit(l2) == want, "l2": first_digit(l2) or "-", "free": free}


def summary(rows):
    lines = ["📊 Digit check: asked → heard (Logic 1 = password_node, Logic 2 = Vosk streaming)"]
    for row in rows:
        lines.append("%s %s → %s %s · L2 %s %s · said \"%s\"" % (
            row["want"], row["word"], row["heard"], "✅" if row["ok1"] else "❌",
            row["l2"], "✅" if row["ok2"] else "❌", row["free"] or "-"))
    ok1 = sum(r["ok1"] for r in rows)
    ok2 = sum(r["ok2"] for r in rows)
    lines.append("Right: Logic 1 %d/%d, Logic 2 %d/%d" % (ok1, len(rows), ok2, len(rows)))
    return "\n".join(lines)


async def send_text(settings, text):
    from telegram import Bot
    async with Bot(settings.token) as bot:
        await bot.send_message(chat_id=settings.chat_id, text=text)


async def send(settings, data, kind, text):
    from telegram import Bot
    async with Bot(settings.token) as bot:
        if kind == "voice":
            await bot.send_voice(chat_id=settings.chat_id, voice=data, caption=text,
                                 write_timeout=15)
        else:
            await bot.send_document(chat_id=settings.chat_id, document=data,
                                    filename="mic_check.wav", caption=text, write_timeout=15)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tries", type=int, default=3, help="tries per gain")
    ap.add_argument("--gain", default="", help="mic capture %% to try, e.g. 40,60,80,100")
    ap.add_argument("--card", type=int, default=2, help="ALSA card (USB audio)")
    ap.add_argument("--device", type=int, default=0, help="PyAudio input device")
    ap.add_argument("--threshold", type=float, default=4000.0,
                    help="password_node's energy_threshold (Logic 1)")
    ap.add_argument("--model", default="/root/share/vosk-model-small-en-us-0.15")
    ap.add_argument("--words", default="hello", help="extra grammar words (vosk_words)")
    ap.add_argument("--env-file", default=os.path.join(ROOT, ".env"))
    ap.add_argument("--no-telegram", action="store_true")
    ap.add_argument("--digits", action="store_true",
                    help='ask "Say zero" ... "Say nine", digits-only word list, summary table')
    args = ap.parse_args()
    if args.digits:
        args.words = ""  # the check listens for digits only

    import speech_recognition as sr
    from vosk import Model, SetLogLevel
    from telegram_alert.settings import load_settings
    from telegram_alert.voice import to_voice

    SetLogLevel(-1)
    model = Model(args.model)
    grammar = vosk_grammar(args.words)
    stored = os.environ.get("ROBOT_PASSWORD_HASH", "")
    verifier = PasswordVerifier(*parse_stored(stored)) if stored and not args.digits else None
    settings = None if args.no_telegram else load_settings(env_file=args.env_file)

    original_gain = get_gain(args.card)
    gains = [int(g) for g in args.gain.split(",") if g.strip()] or [None]
    mic = Mic(args.device)
    n, rows = 0, []
    try:
        for gain in gains:
            if gain is not None:
                set_gain(args.card, gain)
            asks = [w for w in DIGIT_WORDS if w != "oh"] if args.digits else [None] * args.tries
            for word in asks:
                n += 1
                print("try %d: prompt and countdown..." % n, flush=True)
                prompt = (os.path.join(ROOT, "tools", "clips", "say_%s.wav" % word)
                          if word else "password_prompt")
                r = one_try(mic, model, grammar, args.threshold, args.card, prompt)
                text = caption(n, gain if gain is not None else get_gain(args.card),
                               r, verifier, args.threshold)
                if word:
                    row = digit_row(word, r, model)
                    rows.append(row)
                    text = "Asked: %s → heard %s\n" % (word, row["heard"]) + text
                print(text + "\n", flush=True)
                if settings is not None:
                    wav = sr.AudioData(r["raw"], RATE, 2).get_wav_data(convert_rate=16000,
                                                                        convert_width=2)
                    kind, data = to_voice(wav)
                    try:
                        asyncio.run(asyncio.wait_for(send(settings, data, kind, text), 30))
                    except Exception as e:  # keep testing even if one send fails
                        print("telegram send failed: %r" % e, flush=True)
                time.sleep(1.0)
        if rows:
            table = summary(rows)
            print(table, flush=True)
            if settings is not None:
                asyncio.run(asyncio.wait_for(send_text(settings, table), 30))
    finally:
        mic.close()
        if original_gain is not None:
            set_gain(args.card, original_gain)


if __name__ == "__main__":
    main()
