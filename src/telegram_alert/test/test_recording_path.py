"""/password/recording names a file that telegram_node reads, sends and
deletes, so only a WAV straight inside the recording directory is accepted."""

import os

import pytest

from telegram_alert.recording_path import safe_recording_path


def make(tmp_path, name="20261105-101010_1.wav"):
    base = tmp_path / "attempts"
    base.mkdir(exist_ok=True)
    f = base / name
    f.write_bytes(b"RIFF")
    return str(base), str(f)


def test_a_wav_in_the_directory_is_accepted(tmp_path):
    base, path = make(tmp_path)
    assert safe_recording_path(path, base) == os.path.realpath(path)


def test_a_file_outside_the_directory_is_rejected(tmp_path):
    base, _ = make(tmp_path)
    secret = tmp_path / "secret.wav"
    secret.write_bytes(b"x")
    assert safe_recording_path(str(secret), base) is None


def test_dot_dot_out_of_the_directory_is_rejected(tmp_path):
    base, _ = make(tmp_path)
    (tmp_path / "secret.wav").write_bytes(b"x")
    assert safe_recording_path(os.path.join(base, "..", "secret.wav"), base) is None


def test_a_subdirectory_is_rejected(tmp_path):
    base, _ = make(tmp_path)
    sub = os.path.join(base, "sub")
    os.mkdir(sub)
    deep = os.path.join(sub, "a.wav")
    open(deep, "wb").close()
    assert safe_recording_path(deep, base) is None


def test_a_file_that_is_not_wav_is_rejected(tmp_path):
    base, path = make(tmp_path, "notes.txt")
    assert safe_recording_path(path, base) is None


def test_a_symlink_pointing_out_is_rejected(tmp_path):
    base, _ = make(tmp_path)
    target = tmp_path / "secret.wav"
    target.write_bytes(b"x")
    link = os.path.join(base, "link.wav")
    try:
        os.symlink(target, link)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks not available")
    assert safe_recording_path(link, base) is None


@pytest.mark.parametrize("bad", [None, 5, "", ["a.wav"], {"p": 1}])
def test_a_path_that_is_not_text_is_rejected(tmp_path, bad):
    base, _ = make(tmp_path)
    assert safe_recording_path(bad, base) is None
