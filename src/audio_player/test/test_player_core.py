
import threading
from types import SimpleNamespace

import pytest

import audio_player.player_core as player_core
from audio_player.player_core import AudioPlayer


@pytest.fixture
def clips(tmp_path):
    """Create dummy clip files; no speaker needed."""
    names = [
        "found_chair",
        "found_table",
        "password_prompt",
        "alert",
        "blocking",
    ]

    for name in names:
        (tmp_path / f"{name}.wav").write_bytes(b"test")

    return tmp_path


def test_invalid_and_missing_clips(clips):
    player = AudioPlayer(clip_dir=clips)

    try:
        assert not player.request("../secret")
        assert not player.request("not_found")
    finally:
        player.close()


def test_cooldown_only_for_found_clips(clips, monkeypatch):
    monkeypatch.setattr(
        AudioPlayer, "_play_file",
        lambda self, path: False
    )

    player = AudioPlayer(
        cooldown=60.0,
        clip_dir=clips,
    )

    try:
        assert player.request("found_chair")
        assert not player.request("found_chair")

        # Password clips must not be affected
        assert player.request("password_prompt")
        assert player.request("password_prompt")

        assert player.wait_until_idle(timeout=3)
    finally:
        player.close()


def test_queue_order(clips, monkeypatch):
    started = threading.Event()
    release = threading.Event()
    played = []

    def fake_play(self, path):
        played.append(path.stem)

        if path.stem == "found_chair":
            started.set()
            release.wait(timeout=3)

        return False

    monkeypatch.setattr(
        AudioPlayer, "_play_file", fake_play
    )

    player = AudioPlayer(clip_dir=clips)

    try:
        assert player.request("found_chair")
        assert started.wait(timeout=2)

        assert player.request("found_table")
        assert player.request("password_prompt")

        release.set()

        assert player.wait_until_idle(timeout=3)
        assert played == [
            "found_chair",
            "found_table",
            "password_prompt",
        ]
    finally:
        release.set()
        player.close()


def test_alert_interrupts_and_goes_first(clips, monkeypatch):
    started = threading.Event()
    played = []

    def fake_play(self, path):
        played.append(path.stem)

        if path.stem == "found_chair":
            started.set()
            return self.interrupt.wait(timeout=3)

        return False

    monkeypatch.setattr(
        AudioPlayer, "_play_file", fake_play
    )

    player = AudioPlayer(clip_dir=clips)

    try:
        assert player.request("found_chair")
        assert started.wait(timeout=2)

        assert player.request("found_table")
        assert player.request("alert")
        assert player.request("password_prompt")

        assert player.wait_until_idle(timeout=3)

        assert played == [
            "found_chair",
            "alert",
            "found_table",
            "password_prompt",
        ]
    finally:
        player.close()


def test_alert_and_blocking_skip_duplicates(clips, monkeypatch):
    alert_started = threading.Event()
    alert_release = threading.Event()
    blocking_started = threading.Event()
    blocking_release = threading.Event()
    played = []

    def fake_play(self, path):
        played.append(path.stem)

        if path.stem == "alert":
            alert_started.set()
            alert_release.wait(timeout=3)

        elif path.stem == "blocking":
            blocking_started.set()
            blocking_release.wait(timeout=3)

        return False

    monkeypatch.setattr(AudioPlayer, "_play_file", fake_play)

    player = AudioPlayer(clip_dir=clips)

    try:
        # First alert should play
        assert player.request("alert")
        assert alert_started.wait(timeout=2)

        # Duplicate alert while playing must be rejected
        assert not player.request("alert")

        # First blocking should enter the queue
        assert player.request("blocking")

        # Duplicate blocking in queue must be rejected
        assert not player.request("blocking")

        # State machine may repeatedly publish the same pair
        for _ in range(5):
            assert not player.request("alert")
            assert not player.request("blocking")

        # Finish alert and start blocking
        alert_release.set()
        assert blocking_started.wait(timeout=2)

        # Duplicate blocking while playing must be rejected
        assert not player.request("blocking")

        blocking_release.set()

        assert player.wait_until_idle(timeout=3)

        # Only one of each clip should be played
        assert played == ["alert", "blocking"]

    finally:
        alert_release.set()
        blocking_release.set()
        player.close()


def test_aplay_success_and_failure(clips, monkeypatch):
    # Simulate Linux only inside the audio_player module
    monkeypatch.setattr(
        player_core, "os", SimpleNamespace(name="posix")
    )

    class FakeProcess:
        def __init__(self, exit_code):
            self.returncode = exit_code

        def poll(self):
            return self.returncode

    exit_codes = iter([0, 1])

    def fake_popen(command, **kwargs):
        assert command[0] == "aplay"
        return FakeProcess(next(exit_codes))

    monkeypatch.setattr(
        player_core.subprocess, "Popen", fake_popen
    )

    player = AudioPlayer(clip_dir=clips)

    try:
        # Exit code 0 = successful playback
        assert player._play_file(clips / "blocking.wav") is False

        # Exit code 1 = playback failure
        with pytest.raises(
            RuntimeError,
            match="aplay failed with exit code 1"
        ):
            player._play_file(clips / "blocking.wav")

    finally:
        player.close()


def test_aplay_interrupt_terminates_process(clips, monkeypatch):
    monkeypatch.setattr(
        player_core, "os", SimpleNamespace(name="posix")
    )

    processes = []

    class FakeProcess:
        def __init__(self):
            self.returncode = None
            self.terminated = False

        def poll(self):
            return self.returncode

        def terminate(self):
            self.terminated = True
            self.returncode = -15

        def wait(self, timeout=None):
            return self.returncode

    player = AudioPlayer(clip_dir=clips)

    def fake_popen(command, **kwargs):
        assert command[0] == "aplay"

        process = FakeProcess()
        processes.append(process)

        # Simulate an interrupt after playback starts
        player.interrupt.set()
        return process

    monkeypatch.setattr(
        player_core.subprocess, "Popen", fake_popen
    )

    try:
        assert player._play_file(clips / "blocking.wav") is True
        assert len(processes) == 1
        assert processes[0].terminated is True

    finally:
        player.close()


def test_playback_failure_logs_error(clips, monkeypatch, capfd):
    def fake_play_failure(self, path):
        raise RuntimeError("aplay failed with exit code 1")

    monkeypatch.setattr(
        AudioPlayer, "_play_file", fake_play_failure
    )

    player = AudioPlayer(clip_dir=clips)

    try:
        assert player.request("blocking")
        assert player.wait_until_idle(timeout=3)

        output = capfd.readouterr().out

        assert "[ERROR] blocking" in output
        assert "aplay failed with exit code 1" in output
        assert "[DONE] blocking" not in output

    finally:
        player.close()
