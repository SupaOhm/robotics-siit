"""Microphone capture + speech-to-text for the spoken password.

Engines:
  vosk    Offline Vosk model, light enough for a Raspberry Pi. Its vocabulary
          is limited to the digit words plus any ``vosk_words`` set on the
          robot (a word password), which makes them far more reliable
          (default, contract D24). Every mic chunk goes to Vosk from the
          moment the beep ends, and the first phrase it recognises is the
          answer: no loudness threshold (D34).
  google  Google Web Speech via the SpeechRecognition package. Needs internet,
          any words, many languages. Fallback only. Waits for sound louder
          than energy_threshold.

Third-party packages are imported lazily so the parsing helpers can be
tested without them.
"""

import collections
import io
import json
import os
import threading
import wave
from dataclasses import dataclass, field
from typing import List, Optional

ENGINES = ("vosk", "google")

VOSK_RATE = 16000      # samples/s Vosk gets, and the rate of the recordings (D32)
CHUNK = 1024           # frames per mic read
MIC_BUFFER_S = 2.0     # newest audio kept while nobody listens
MIC_STALL = 2.0        # no audio this long -> the mic is dead
MIC_CLOSE_WAIT = 0.2   # s for the reader to finish its read before closing

# Vosk grammar: only these words can be recognized; anything else -> "[unk]".
DIGIT_WORDS = ["zero", "oh", "one", "two", "three", "four", "five", "six",
               "seven", "eight", "nine"]
VOSK_GRAMMAR = json.dumps(DIGIT_WORDS + ["[unk]"])


def vosk_grammar(extra_words: str = "", free_speech: bool = False) -> Optional[str]:
    """The grammar with extra words ("hello, banana") for a word password.
    They're set on the robot, not in the repo: the password is one of them.
    With free_speech there is no grammar: Vosk hears any English, so the
    operator reads what the person really said (D32)."""
    if free_speech:
        return None
    extra = [w for w in extra_words.lower().replace(",", " ").split() if w]
    return json.dumps(DIGIT_WORDS + extra + ["[unk]"])


@dataclass
class ListenResult:
    kind: str                      # "speech" | "no_speech" | "error"
    candidates: List[str] = field(default_factory=list)
    error: str = ""
    wav: bytes = b""               # the answer as heard, for the operator (D32)
    free_text: str = ""            # free-speech transcript, for the caption only (D24)


def google_candidates(response) -> List[str]:
    """Transcripts from a recognize_google(show_all=True) response."""
    if not isinstance(response, dict):
        return []  # the library returns [] when nothing was recognized
    alternatives = response.get("alternative") or []
    return [a["transcript"] for a in alternatives
            if isinstance(a, dict) and a.get("transcript")]


def vosk_candidates(result_json: str) -> List[str]:
    """Transcripts from a Vosk FinalResult() JSON string."""
    data = json.loads(result_json or "{}")
    if "alternatives" in data:
        texts = [a.get("text", "") for a in data["alternatives"]]
    else:
        texts = [data.get("text", "")]
    # "[unk]" marks a non-digit word; drop it so "[unk]" alone counts as unclear
    texts = [" ".join(w for w in t.split() if w != "[unk]") for t in texts]
    return [t for t in texts if t]


def vosk_heard_words(result_json: str) -> bool:
    """True if Vosk heard any word, even one it can only call "[unk]".
    Takes a Result(), FinalResult() or PartialResult() JSON string."""
    data = json.loads(result_json or "{}")
    texts = [a.get("text", "") for a in data.get("alternatives", [])]
    texts += [data.get("text", ""), data.get("partial", "")]
    return any(t.strip() for t in texts)


def listen_stream(chunks, rec, cancel=None, listen_timeout: float = 6.0,
                  window: float = 11.0):
    """Feed 16 kHz chunks to a Vosk recogniser until there's an answer (D34).
    Returns (kind, candidates, pcm), where kind is "speech" or "no_speech".

    The first phrase with a word from the grammar is the answer. "[unk]"
    means someone spoke, so it keeps listening, and only "[unk]" by the end
    of the window is unclear speech with its clip (D32). No word by
    listen_timeout is silence. Time is counted by the audio fed."""
    kept = bytearray()
    started = False
    for pcm in chunks:
        if cancel is not None and cancel.is_set():
            return "no_speech", [], b""  # run_session drops it anyway
        kept += pcm
        if rec.AcceptWaveform(pcm):
            result = rec.Result()
            found = vosk_candidates(result)
            if found:
                return "speech", found, bytes(kept)
            started = started or vosk_heard_words(result)
        seconds = len(kept) / (2 * VOSK_RATE)
        if not started and seconds >= listen_timeout:
            # A phrase in progress has no Result() yet
            if not vosk_heard_words(rec.PartialResult()):
                return "no_speech", [], b""
            started = True
        if seconds >= window:
            break
    final = rec.FinalResult()
    found = vosk_candidates(final)
    if found:
        return "speech", found, bytes(kept)
    if started or vosk_heard_words(final):
        return "speech", [], bytes(kept)
    return "no_speech", [], b""


def pcm_to_wav(pcm: bytes) -> bytes:
    """16 kHz 16-bit mono WAV, as the operator gets it (D32)."""
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(VOSK_RATE)
        w.writeframes(pcm)
    return out.getvalue()


class MicStalled(Exception):
    """No audio from the mic for MIC_STALL seconds."""


class MicStream:
    """The mic, opened once; a thread reads it into a capped buffer (D34).
    Re-opening it for each try hung on the robot, and a read that hangs here
    shows up as MicStalled instead of blocking the session."""

    def __init__(self, device_index: Optional[int] = None,
                 sample_rate: Optional[int] = None):
        import pyaudio
        self._pa = pyaudio.PyAudio()
        try:
            self.rate = sample_rate or int(self._device_info(device_index)["defaultSampleRate"])
            self._stream = self._pa.open(
                format=pyaudio.paInt16, channels=1, rate=self.rate, input=True,
                input_device_index=device_index, frames_per_buffer=CHUNK)
        except Exception:
            self._pa.terminate()
            raise
        self._chunks = collections.deque(maxlen=int(MIC_BUFFER_S * self.rate / CHUNK))
        self._ready = threading.Condition()
        self._running = True
        self._reader = threading.Thread(target=self._read, daemon=True)
        self._reader.start()

    def _device_info(self, device_index):
        if device_index is None:
            return self._pa.get_default_input_device_info()
        return self._pa.get_device_info_by_index(device_index)

    def _read(self):
        while self._running:
            try:
                raw = self._stream.read(CHUNK, exception_on_overflow=False)
            except Exception:
                return  # the listener sees no more audio: MicStalled
            with self._ready:
                self._chunks.append(raw)
                self._ready.notify()

    def flush(self) -> None:
        """Drop what was heard so far: the robot's own countdown (D33)."""
        with self._ready:
            self._chunks.clear()

    def next(self, timeout: float) -> bytes:
        with self._ready:
            if not self._ready.wait_for(lambda: self._chunks, timeout):
                raise MicStalled("no audio for %.1f s" % timeout)
            return self._chunks.popleft()

    def chunks_16k(self):
        """The mic's audio from now on, resampled for Vosk."""
        import audioop
        state = None
        while True:
            pcm, state = audioop.ratecv(self.next(MIC_STALL), 2, 1, self.rate,
                                        VOSK_RATE, state)
            yield pcm

    def close(self) -> None:
        self._running = False
        self._reader.join(MIC_CLOSE_WAIT)
        if self._reader.is_alive():
            return  # stuck in a read: closing under it could crash PortAudio
        try:
            self._stream.close()
        finally:
            self._pa.terminate()


class SpeechListener:
    def __init__(
        self,
        engine: str = "vosk",
        language: str = "en-US",
        device_index: Optional[int] = None,
        sample_rate: Optional[int] = None,
        listen_timeout: float = 6.0,
        phrase_time_limit: float = 5.0,
        vosk_model_path: str = "",
        operation_timeout: float = 10.0,
        energy_threshold: float = 0.0,
        vosk_words: str = "",
        vosk_free_speech: bool = False,
    ):
        if engine not in ENGINES:
            raise ValueError("engine must be one of %s" % (ENGINES,))
        import speech_recognition as sr
        self._sr = sr
        self.engine = engine
        self.language = language
        self.device_index = device_index
        # None = the device's default. The robot's USB mic needs 48000: at
        # its default 44100 it delivers only ~24,300 samples/s, so speech is
        # stored 1.8x fast and Vosk hears a chipmunk
        self.sample_rate = sample_rate
        self.listen_timeout = listen_timeout
        self.phrase_time_limit = phrase_time_limit
        self.recognizer = sr.Recognizer()
        # Google only. Fixed threshold, set by calibrate() or energy_threshold. The dynamic
        # one also rises *during* speech (SpeechRecognition 3.17), so a softer
        # last digit counted as silence and was cut off: "zero zero eight six"
        # was heard as "zero zero eight".
        self.recognizer.dynamic_energy_threshold = False
        if energy_threshold > 0:
            self.recognizer.energy_threshold = energy_threshold
        # Google only: give up on a dropped connection instead of hanging
        self.recognizer.operation_timeout = operation_timeout

        # The check always listens for digits (+ vosk_words): free speech
        # misheard accented speech on the robot (Nov 5). vosk_free_speech only
        # adds a second pass for the Telegram caption (D24)
        self._grammar = vosk_grammar(vosk_words)
        self.free_speech = vosk_free_speech
        self._vosk_model = None
        self._mic = None
        if engine == "vosk":
            # No download at startup: the venue may have no internet.
            if not vosk_model_path or not os.path.isdir(vosk_model_path):
                raise ValueError(
                    "vosk_model_path must point to an unzipped Vosk model folder "
                    "(got %r). Download vosk-model-small-en-us-0.15 once, see the "
                    "README." % vosk_model_path)
            from vosk import Model, SetLogLevel
            SetLogLevel(-1)
            self._vosk_model = Model(vosk_model_path)

    def _microphone(self):
        return self._sr.Microphone(device_index=self.device_index, sample_rate=self.sample_rate)

    def calibrate(self, seconds: float = 1.0) -> None:
        """Measure background noise to set the (fixed) speech energy threshold.
        Google only. Raises if the microphone can't be opened."""
        with self._microphone() as source:
            self.recognizer.adjust_for_ambient_noise(source, duration=seconds)

    def open_mic(self) -> MicStream:
        """Vosk: open the mic and keep it open. Raises if it can't be opened."""
        if self._mic is None:
            self._mic = MicStream(self.device_index, self.sample_rate)
        return self._mic

    def close_mic(self) -> None:
        mic, self._mic = self._mic, None
        if mic is not None:
            mic.close()

    def listen_once(self, cancel=None) -> ListenResult:
        """Block until one answer is heard (or timeout). ``cancel`` is the
        session's event; Vosk checks it between chunks, so a cancelled listen
        ends at once. Never raises: any failure comes back as kind "error"."""
        if self.engine == "vosk":
            return self._listen_vosk(cancel)
        return self._listen_google()

    def _listen_vosk(self, cancel) -> ListenResult:
        try:
            mic = self.open_mic()
        except Exception as e:  # missing, busy, ...
            return ListenResult("error", error="microphone: %r" % e)
        mic.flush()
        try:
            from vosk import KaldiRecognizer
            args = (self._grammar,) if self._grammar else ()
            rec = KaldiRecognizer(self._vosk_model, VOSK_RATE, *args)
            rec.SetMaxAlternatives(3)
            kind, candidates, pcm = listen_stream(
                mic.chunks_16k(), rec, cancel, self.listen_timeout,
                self.listen_timeout + self.phrase_time_limit)
        except MicStalled as e:
            self.close_mic()  # the next listen opens a new one
            return ListenResult("error", error="microphone: %r" % e)
        except Exception as e:
            return ListenResult("error", error="speech engine: %r" % e)
        if kind != "speech":
            return ListenResult(kind)
        return ListenResult(kind, candidates, wav=pcm_to_wav(pcm), free_text=self.free_text(pcm))

    def _listen_google(self) -> ListenResult:
        sr = self._sr
        try:
            with self._microphone() as source:
                audio = self.recognizer.listen(
                    source, timeout=self.listen_timeout,
                    phrase_time_limit=self.phrase_time_limit)
        except sr.WaitTimeoutError:
            return ListenResult("no_speech")
        except Exception as e:  # mic missing or busy (OSError, AttributeError, ...)
            return ListenResult("error", error="microphone: %r" % e)

        wav = audio.get_wav_data(convert_rate=16000, convert_width=2)
        try:
            return ListenResult("speech", self.transcribe(audio), wav=wav)
        except sr.UnknownValueError:
            return ListenResult("speech", [], wav=wav)
        except Exception as e:  # RequestError, no flac binary, ...
            return ListenResult("error", error="speech engine: %r" % e)

    def transcribe(self, audio) -> List[str]:
        response = self.recognizer.recognize_google(
            audio, language=self.language, show_all=True)
        return google_candidates(response)

    def free_text(self, pcm: bytes) -> str:
        """What was said, in any English words (Vosk without a word list).
        For the operator's caption only, never for the check, so a failure
        here only leaves the caption empty."""
        if not self.free_speech:
            return ""
        try:
            from vosk import KaldiRecognizer
            rec = KaldiRecognizer(self._vosk_model, VOSK_RATE)
            rec.SetMaxAlternatives(3)
            rec.AcceptWaveform(pcm)
            found = vosk_candidates(rec.FinalResult())
        except Exception:
            return ""
        return found[0] if found else ""
