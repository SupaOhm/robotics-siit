"""Microphone capture + speech-to-text for the spoken password.

Engines:
  vosk    Offline Vosk model, light enough for a Raspberry Pi. Its vocabulary
          is limited to the digit words, which makes digits far more reliable
          (default, contract D24).
  google  Google Web Speech via the SpeechRecognition package. Needs internet,
          any words, many languages. Fallback only.

Third-party packages are imported lazily so the parsing helpers can be
tested without them.
"""

import json
import os
from dataclasses import dataclass, field
from typing import List, Optional

ENGINES = ("vosk", "google")

# Vosk grammar: only these words can be recognized; anything else -> "[unk]".
DIGIT_WORDS = ["zero", "oh", "one", "two", "three", "four", "five", "six",
               "seven", "eight", "nine"]
VOSK_GRAMMAR = json.dumps(DIGIT_WORDS + ["[unk]"])


@dataclass
class ListenResult:
    kind: str                      # "speech" | "no_speech" | "error"
    candidates: List[str] = field(default_factory=list)
    error: str = ""


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


class SpeechListener:
    def __init__(
        self,
        engine: str = "vosk",
        language: str = "en-US",
        device_index: Optional[int] = None,
        listen_timeout: float = 6.0,
        phrase_time_limit: float = 5.0,
        vosk_model_path: str = "",
        operation_timeout: float = 10.0,
    ):
        if engine not in ENGINES:
            raise ValueError("engine must be one of %s" % (ENGINES,))
        import speech_recognition as sr
        self._sr = sr
        self.engine = engine
        self.language = language
        self.device_index = device_index
        self.listen_timeout = listen_timeout
        self.phrase_time_limit = phrase_time_limit
        self.recognizer = sr.Recognizer()
        self.recognizer.dynamic_energy_threshold = True
        # Google only: give up on a dropped connection instead of hanging
        self.recognizer.operation_timeout = operation_timeout

        self._vosk_model = None
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
        return self._sr.Microphone(device_index=self.device_index)

    def calibrate(self, seconds: float = 1.0) -> None:
        """Measure background noise to set the speech energy threshold.
        Raises if the microphone can't be opened."""
        with self._microphone() as source:
            self.recognizer.adjust_for_ambient_noise(source, duration=seconds)

    def listen_once(self) -> ListenResult:
        """Block until one phrase is heard (or timeout), then transcribe it.
        Never raises: any failure comes back as kind "error"."""
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

        try:
            return ListenResult("speech", self.transcribe(audio))
        except sr.UnknownValueError:
            return ListenResult("speech", [])
        except Exception as e:  # RequestError, no flac binary, ...
            return ListenResult("error", error="speech engine: %r" % e)

    def transcribe(self, audio) -> List[str]:
        if self.engine == "google":
            response = self.recognizer.recognize_google(
                audio, language=self.language, show_all=True)
            return google_candidates(response)

        from vosk import KaldiRecognizer
        rec = KaldiRecognizer(self._vosk_model, 16000, VOSK_GRAMMAR)
        rec.SetMaxAlternatives(3)
        rec.AcceptWaveform(audio.get_raw_data(convert_rate=16000, convert_width=2))
        return vosk_candidates(rec.FinalResult())
