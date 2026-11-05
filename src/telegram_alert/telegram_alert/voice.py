"""A failed password answer (D32) as something Telegram can play.

Telegram plays OGG/Opus inline as a voice message, so the WAV goes through
ffmpeg. Without ffmpeg (or if it fails) the WAV is sent as a file instead:
the operator still hears it, with one more tap.
"""

import subprocess
from typing import Tuple

FFMPEG = ["ffmpeg", "-loglevel", "error", "-i", "pipe:0",
          "-c:a", "libopus", "-b:a", "32k", "-f", "ogg", "pipe:1"]


def to_voice(wav: bytes) -> Tuple[str, bytes]:
    """("voice", ogg bytes), or ("document", the wav) if ffmpeg can't."""
    try:
        done = subprocess.run(FFMPEG, input=wav, capture_output=True,
                              timeout=10, check=True)
        return "voice", done.stdout
    except (OSError, subprocess.SubprocessError):
        return "document", wav
