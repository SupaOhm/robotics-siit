"""Which file a /password/recording message may name."""

import os


def safe_recording_path(path, recording_dir):
    """The resolved path if `path` is a .wav straight inside `recording_dir`,
    else None. Symlinks are resolved first, so a link out of the directory
    fails. The message comes off the ROS network and the node reads, sends
    and deletes the file it names."""
    if not isinstance(path, str) or not path:
        return None
    real = os.path.realpath(path)
    base = os.path.realpath(os.path.expanduser(recording_dir))
    if os.path.dirname(real) != base or not real.endswith(".wav"):
        return None
    return real
