"""D34: password_node listens with Vosk streaming, no loudness threshold.
A fake recogniser and a fake mic, so no Vosk, PortAudio or sleeps."""

import io
import json
import sys
import threading
import time
import wave
from types import SimpleNamespace

import pytest

from password_system import speech
from password_system.speech import MicStalled, MicStream, listen_stream

HALF_S = b"\0\0" * 8000  # 0.5 s at 16 kHz, 16-bit


class FakeRec:
    """Recogniser scripted by chunk number: {2: "four two"} ends a phrase on
    the 2nd chunk. ``partial`` is what is in progress at the deadline."""

    def __init__(self, phrases=None, partial="", final=""):
        self.phrases = phrases or {}
        self.partial = partial
        self.final = final
        self.fed = 0

    def AcceptWaveform(self, pcm):
        self.fed += 1
        return self.fed in self.phrases

    def Result(self):
        return json.dumps({"alternatives": [{"confidence": 1.0,
                                             "text": self.phrases[self.fed]}]})

    def PartialResult(self):
        return json.dumps({"partial": self.partial})

    def FinalResult(self):
        return json.dumps({"alternatives": [{"confidence": 1.0, "text": self.final}]})


def chunks(n=100):
    return iter([HALF_S] * n)


def run(rec, cancel=None, source=None):
    return listen_stream(chunks() if source is None else source, rec, cancel,
                         listen_timeout=6.0, window=11.0)


def test_first_digit_phrase_is_the_answer():
    rec = FakeRec({3: "four two"})
    assert run(rec) == ("speech", ["four two"], HALF_S * 3)
    assert rec.fed == 3  # stops at once: no waiting for the window


def test_unk_only_phrase_keeps_listening_for_the_digits():
    rec = FakeRec({2: "[unk]", 5: "[unk] four two"})
    assert run(rec)[:2] == ("speech", ["four two"])
    assert rec.fed == 5


def test_only_unk_is_unclear_with_the_clip_not_silence():
    # D32: silence has no recording, an unclear answer does
    rec = FakeRec({2: "[unk]"})
    kind, candidates, pcm = run(rec)
    assert (kind, candidates) == ("speech", [])
    assert pcm == HALF_S * 22  # the whole 11 s window
    assert rec.fed == 22


def test_no_words_in_6_s_is_no_speech():
    rec = FakeRec()
    assert run(rec) == ("no_speech", [], b"")
    assert rec.fed == 12  # counted by audio fed, not the wall clock


def test_empty_phrases_are_not_words():
    rec = FakeRec({2: "", 4: ""})
    assert run(rec)[0] == "no_speech"
    assert rec.fed == 12


def test_a_word_in_progress_at_6_s_is_not_silence():
    # started at 5.5 s: no Result() yet, only a partial
    rec = FakeRec(partial="four", final="four two")
    assert run(rec)[:2] == ("speech", ["four two"])
    assert rec.fed == 22


def test_unk_in_progress_at_6_s_is_not_silence():
    rec = FakeRec(partial="[unk]")
    assert run(rec)[:2] == ("speech", [])
    assert rec.fed == 22


def test_final_result_with_only_unk_is_unclear():
    rec = FakeRec(partial="[unk]", final="[unk]")
    assert run(rec)[:2] == ("speech", [])


def test_nothing_at_the_end_of_the_audio_is_no_speech():
    assert run(FakeRec(), source=chunks(3)) == ("no_speech", [], b"")


def test_a_word_password_counts_like_digits():
    # D23: vosk_words joins the grammar, so it is a recognised phrase too
    assert run(FakeRec({2: "banana"}))[:2] == ("speech", ["banana"])


def test_cancel_stops_within_one_chunk():
    cancel = threading.Event()
    rec = FakeRec()

    def source():
        yield HALF_S
        yield HALF_S
        cancel.set()
        yield HALF_S
        pytest.fail("kept reading after the cancel")

    assert run(rec, cancel, source()) == ("no_speech", [], b"")
    assert rec.fed == 2


class FakeStream:
    def __init__(self, read):
        self._read = read
        self.reads = 0
        self.closed = False

    def read(self, n, exception_on_overflow=True):
        assert exception_on_overflow is False
        self.reads += 1
        return self._read(self, n)

    def close(self):
        self.closed = True


def steady(stream, n):
    time.sleep(0.0005)
    return b"\0\0" * n


class Hang:
    """A read that never returns, until the test ends."""

    def __init__(self):
        self.release = threading.Event()

    def __call__(self, stream, n):
        self.release.wait(5.0)
        raise OSError("released")


@pytest.fixture
def pyaudio(monkeypatch):
    """A fake PyAudio; ``reads`` is what each opened stream does."""
    fake = SimpleNamespace(paInt16=8, reads=[], opened=[], streams=[], open_error=None,
                           terminated=0)

    class PyAudio:
        def get_default_input_device_info(self):
            return {"defaultSampleRate": 44100.0}

        def get_device_info_by_index(self, index):
            return {"defaultSampleRate": 32000.0}

        def open(self, **kw):
            if fake.open_error:
                raise fake.open_error
            fake.opened.append(kw)
            stream = FakeStream(fake.reads.pop(0) if fake.reads else steady)
            fake.streams.append(stream)
            return stream

        def terminate(self):
            fake.terminated += 1

    fake.PyAudio = PyAudio
    monkeypatch.setitem(sys.modules, "pyaudio", fake)
    return fake


def wait_for(condition):
    deadline = time.monotonic() + 2.0
    while not condition():
        assert time.monotonic() < deadline, "timed out"
        time.sleep(0.001)


def test_mic_opens_at_the_set_rate_or_the_device_default(pyaudio):
    for args, rate in (((0, 48000), 48000), ((None, None), 44100), ((0, None), 32000)):
        mic = MicStream(*args)
        assert mic.rate == rate
        assert pyaudio.opened[-1]["rate"] == rate
        assert pyaudio.opened[-1]["channels"] == 1
        mic.close()


def test_buffer_is_capped_so_it_cannot_grow_while_nobody_listens(pyaudio):
    mic = MicStream(0, 48000)
    cap = mic._chunks.maxlen
    assert cap
    wait_for(lambda: pyaudio.streams[0].reads > cap + 5)
    assert len(mic._chunks) <= cap
    mic.close()


def test_flush_drops_the_audio_from_before_the_beep(pyaudio):
    def numbered(stream, n):
        time.sleep(0.0005)
        return bytes([min(stream.reads, 255)]) * 2 * n
    pyaudio.reads = [numbered]
    mic = MicStream(0, 48000)
    wait_for(lambda: pyaudio.streams[0].reads >= 3)
    seen = pyaudio.streams[0].reads  # at most this one is still on its way
    mic.flush()
    assert mic.next(1.0)[0] >= seen
    mic.close()


def test_a_mic_that_stops_delivering_is_a_stall(pyaudio):
    hang = Hang()
    pyaudio.reads = [hang]
    mic = MicStream(0, 48000)
    with pytest.raises(MicStalled):
        mic.next(0.01)
    hang.release.set()


def test_a_read_error_is_a_stall(pyaudio):
    def broken(stream, n):
        raise OSError("device gone")
    pyaudio.reads = [broken]
    mic = MicStream(0, 48000)
    with pytest.raises(MicStalled):
        mic.next(0.01)


def test_close_never_touches_a_stream_stuck_in_a_read(pyaudio, monkeypatch):
    monkeypatch.setattr(speech, "MIC_CLOSE_WAIT", 0.01)
    hang = Hang()
    pyaudio.reads = [hang]
    mic = MicStream(0, 48000)
    wait_for(lambda: pyaudio.streams[0].reads == 1)
    mic.close()
    assert pyaudio.streams[0].closed is False
    hang.release.set()


def test_close_releases_a_healthy_mic(pyaudio):
    mic = MicStream(0, 48000)
    mic.close()
    assert pyaudio.streams[0].closed is True
    assert pyaudio.terminated == 1


class Vosk:
    """Fake vosk: the grammar recogniser hears ``heard`` on its first chunk."""

    def __init__(self, heard="four two", free="for too"):
        self.heard = heard
        self.free = free
        self.grammars = []
        self.free_error = None
        outer = self

        class Rec:
            def __init__(self, model, rate, *grammar):
                assert rate == 16000
                outer.grammars.append(grammar[0] if grammar else None)
                self.is_free = not grammar
                if self.is_free and outer.free_error:
                    raise outer.free_error

            def SetMaxAlternatives(self, n):
                pass

            def AcceptWaveform(self, pcm):
                return bool(outer.heard) and not self.is_free

            def Result(self):
                return json.dumps({"text": outer.heard})

            def PartialResult(self):
                return json.dumps({"partial": ""})

            def FinalResult(self):
                return json.dumps({"text": outer.free if self.is_free else ""})

        self.KaldiRecognizer = Rec
        self.Model = lambda path: "model"
        self.SetLogLevel = lambda n: None


@pytest.fixture
def listener(monkeypatch, tmp_path, pyaudio):
    pytest.importorskip("audioop")
    vosk = Vosk()
    monkeypatch.setitem(sys.modules, "vosk", vosk)
    monkeypatch.setitem(sys.modules, "speech_recognition",
                        SimpleNamespace(Recognizer=lambda: SimpleNamespace()))
    made = speech.SpeechListener(engine="vosk", vosk_model_path=str(tmp_path), device_index=0,
                                 sample_rate=48000, vosk_free_speech=True)
    made.vosk = vosk
    yield made
    made.close_mic()


def test_listen_once_returns_the_answer_and_a_16k_wav(listener):
    result = listener.listen_once()
    assert (result.kind, result.candidates) == ("speech", ["four two"])
    with wave.open(io.BytesIO(result.wav)) as w:
        assert (w.getframerate(), w.getnchannels(), w.getsampwidth()) == (16000, 1, 2)
        assert w.getnframes() > 0


def test_free_speech_only_fills_the_caption(listener):
    # D24: free speech misheard accented speech, so the check is the grammar
    result = listener.listen_once()
    assert result.candidates == ["four two"]
    assert result.free_text == "for too"
    assert json.loads(listener.vosk.grammars[0]) == json.loads(speech.VOSK_GRAMMAR)
    assert listener.vosk.grammars[1:] == [None]  # one free pass, not a second stream


def test_no_free_pass_when_free_speech_is_off(listener):
    listener.free_speech = False
    assert listener.listen_once().free_text == ""
    assert len(listener.vosk.grammars) == 1


def test_a_caption_failure_never_costs_the_answer(listener):
    listener.vosk.free_error = RuntimeError("no memory")
    result = listener.listen_once()
    assert (result.kind, result.candidates) == ("speech", ["four two"])
    assert result.free_text == ""


def test_silence_has_no_recording(listener):
    listener.vosk.heard = ""
    listener.listen_timeout = 0.05
    result = listener.listen_once()
    assert (result.kind, result.wav, result.free_text) == ("no_speech", b"", "")


def test_cancel_reaches_the_loop(listener):
    listener.vosk.heard = ""
    cancel = threading.Event()
    cancel.set()
    assert listener.listen_once(cancel).kind == "no_speech"


def test_mic_stays_open_between_attempts(listener, pyaudio):
    listener.listen_once()
    listener.listen_once()
    assert len(pyaudio.opened) == 1


def test_a_stall_is_an_error_and_the_next_listen_reopens(listener, pyaudio, monkeypatch):
    monkeypatch.setattr(speech, "MIC_STALL", 0.01)
    monkeypatch.setattr(speech, "MIC_CLOSE_WAIT", 0.01)
    hang = Hang()
    pyaudio.reads = [hang]
    result = listener.listen_once()
    assert result.kind == "error" and "microphone" in result.error
    hang.release.set()
    assert listener.listen_once().kind == "speech"
    assert len(pyaudio.opened) == 2


def test_a_mic_that_will_not_open_is_an_error_not_a_crash(listener, pyaudio):
    pyaudio.open_error = OSError("no device")
    result = listener.listen_once()
    assert result.kind == "error" and "microphone" in result.error
