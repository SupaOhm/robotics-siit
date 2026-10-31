
import threading

import pytest

from audio_player.player_core import AudioPlayer


@pytest.fixture
def clips(tmp_path):
    """Create dummy clip files; no speaker needed."""
    names = [
        "found_chair",
        "found_table",
        "password_prompt",
        "alert",
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
