"""Failed password answers (D32) become Telegram voice messages when ffmpeg
is there, and a .wav file otherwise."""

import subprocess
from types import SimpleNamespace

from telegram_alert import voice


def test_ffmpeg_makes_a_voice_message(monkeypatch):
    seen = {}

    def run(cmd, input, capture_output, timeout, check):
        seen["cmd"], seen["input"] = cmd, input
        return SimpleNamespace(stdout=b"OggS...")

    monkeypatch.setattr(voice.subprocess, "run", run)
    assert voice.to_voice(b"RIFF") == ("voice", b"OggS...")
    assert seen["input"] == b"RIFF" and "libopus" in seen["cmd"]


def test_no_ffmpeg_sends_the_wav(monkeypatch):
    def run(*args, **kwargs):
        raise FileNotFoundError("ffmpeg")

    monkeypatch.setattr(voice.subprocess, "run", run)
    assert voice.to_voice(b"RIFF") == ("document", b"RIFF")


def test_ffmpeg_failure_sends_the_wav(monkeypatch):
    def run(*args, **kwargs):
        raise subprocess.CalledProcessError(1, "ffmpeg")

    monkeypatch.setattr(voice.subprocess, "run", run)
    assert voice.to_voice(b"RIFF") == ("document", b"RIFF")
