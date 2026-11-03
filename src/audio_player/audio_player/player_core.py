import os
import re
import subprocess
import threading
import time
import wave
from collections import deque
from pathlib import Path


class AudioPlayer:
    def __init__(self, cooldown=5.0, clip_dir=None, logger=None):
        self.clip_dir = (
            Path(clip_dir)
            if clip_dir is not None
            else Path(__file__).resolve().parent.parent / "clips"
        )
        self.cooldown = cooldown
        self.logger = logger

        self.queue = deque()
        self.last_found = {}

        self.condition = threading.Condition()
        self.interrupt = threading.Event()

        self.closed = False
        self.playing = False
        self.current_clip = None

        self.worker = threading.Thread(
            target=self._worker,
            daemon=True
        )
        self.worker.start()

    def _log(self, message, level="info"):
        if self.logger is None:
            print(message, flush=True)
        elif level == "error":
            self.logger.error(message)
        elif level == "warning":
            self.logger.warning(message)
        else:
            self.logger.info(message)

    def request(self, clip_id):
        # Accept only safe clip IDs, not arbitrary file paths
        if not re.fullmatch(r"[a-z][a-z0-9_]*", clip_id):
            self._log(f"[INVALID] {clip_id}", "warning")
            return False

        path = self.clip_dir / f"{clip_id}.wav"

        if not path.is_file():
            self._log(f"[MISSING] {clip_id}", "warning")
            return False

        with self.condition:
            if self.closed:
                return False
            # Do not queue duplicate alert or blocking clips
            if clip_id in ("alert", "blocking"):
                if clip_id == self.current_clip or clip_id in self.queue:
                    self._log(f"[DUPLICATE] {clip_id}", "info")
                    return False

            now = time.monotonic()

            # Cooldown applies ONLY to found_* clips
            if clip_id.startswith("found_"):
                # Avoid duplicates while queued or playing.
                if clip_id == self.current_clip or clip_id in self.queue:
                    self._log(f"[DUPLICATE] {clip_id}", "info")
                    return False

                last = self.last_found.get(clip_id, -float("inf"))
                if now - last < self.cooldown:
                    self._log(f"[COOLDOWN] {clip_id}", "info")
                    return False

            if clip_id == "alert":
                # Alert jumps to the front and interrupts playback
                self.queue.appendleft(clip_id)
                self.interrupt.set()
            else:
                self.queue.append(clip_id)

            self._log(f"[QUEUED] {clip_id}", "info")
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
        # Check whether aplay actually succeeded
        if process.returncode != 0:
            raise RuntimeError(
                f"aplay failed with exit code {process.returncode}"
            )
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
                self.current_clip = clip_id

            self._log(f"[PLAY] {clip_id}", "info")

            try:
                interrupted = self._play_file(
                    self.clip_dir / f"{clip_id}.wav"
                )

                if interrupted:
                    self._log(f"[INTERRUPTED] {clip_id}", "info")
                else:
                    if clip_id.startswith("found_"):
                        with self.condition:
                            self.last_found[clip_id] = time.monotonic()
                    self._log(f"[DONE] {clip_id}", "info")

            except Exception as error:
                self._log(f"[ERROR] {clip_id}: {error}", "error")

            finally:
                with self.condition:
                    self.playing = False
                    self.current_clip = None
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
