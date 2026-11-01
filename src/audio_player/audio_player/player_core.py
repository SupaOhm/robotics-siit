import os
import re
import subprocess
import threading
import time
import wave
from collections import deque
from pathlib import Path


class AudioPlayer:
    def __init__(self, cooldown=5.0, clip_dir=None):
        self.clip_dir = (
            Path(clip_dir)
            if clip_dir is not None
            else Path(__file__).resolve().parent.parent / "clips"
        )
        self.cooldown = cooldown

        self.queue = deque()
        self.last_found = {}

        self.condition = threading.Condition()
        self.interrupt = threading.Event()

        self.closed = False
        self.playing = False

        self.worker = threading.Thread(
            target=self._worker,
            daemon=True
        )
        self.worker.start()

    def request(self, clip_id):
        # Accept only safe clip IDs, not arbitrary file paths
        if not re.fullmatch(r"[a-z][a-z0-9_]*", clip_id):
            print(f"[INVALID] {clip_id}", flush=True)
            return False

        path = self.clip_dir / f"{clip_id}.wav"

        if not path.is_file():
            print(f"[MISSING] {clip_id}", flush=True)
            return False

        with self.condition:
            if self.closed:
                return False

            now = time.monotonic()

            # Cooldown applies ONLY to found_* clips
            if clip_id.startswith("found_"):
                last = self.last_found.get(clip_id, -float("inf"))

                if now - last < self.cooldown:
                    print(f"[COOLDOWN] {clip_id}", flush=True)
                    return False

                self.last_found[clip_id] = now

            if clip_id == "alert":
                # Alert jumps to the front and interrupts playback
                self.queue.appendleft(clip_id)
                self.interrupt.set()
            else:
                self.queue.append(clip_id)

            print(f"[QUEUED] {clip_id}", flush=True)
            self.condition.notify()
            return True

    def _play_file(self, path):
        if self.interrupt.is_set():
            return True

        if os.name == "nt":
            import winsound

            with wave.open(str(path), "rb") as wav:
                duration = wav.getnframes() / wav.getframerate()

            winsound.PlaySound(
                str(path),
                winsound.SND_FILENAME | winsound.SND_ASYNC
            )

            interrupted = self.interrupt.wait(duration + 0.05)
            winsound.PlaySound(None, 0)
            return interrupted

        # Raspberry Pi / Ubuntu: use ALSA audio player
        process = subprocess.Popen(
            ["aplay", "-q", str(path)],
            stdout=subprocess.DEVNULL
        )

        while process.poll() is None:
            if self.interrupt.wait(0.05):
                process.terminate()
                try:
                    process.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
                return True

        return False

    def _worker(self):
        while True:
            with self.condition:
                while not self.queue and not self.closed:
                    self.condition.wait()

                if self.closed:
                    return

                clip_id = self.queue.popleft()
                self.interrupt.clear()
                self.playing = True

            print(f"[PLAY] {clip_id}", flush=True)

            try:
                interrupted = self._play_file(
                    self.clip_dir / f"{clip_id}.wav"
                )

                if interrupted:
                    print(f"[INTERRUPTED] {clip_id}", flush=True)
                else:
                    print(f"[DONE] {clip_id}", flush=True)

            except Exception as error:
                print(f"[ERROR] {clip_id}: {error}", flush=True)

            finally:
                with self.condition:
                    self.playing = False
                    self.condition.notify_all()

    def wait_until_idle(self, timeout=30):
        with self.condition:
            return self.condition.wait_for(
                lambda: not self.queue and not self.playing,
                timeout=timeout
            )

    def close(self):
        with self.condition:
            self.closed = True
            self.interrupt.set()
            self.queue.clear()
            self.condition.notify_all()

        self.worker.join(timeout=2)
