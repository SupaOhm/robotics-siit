"""telegram_node must survive a broken camera stack: the alert matters more
than the photo. rclpy, cv2 and cv_bridge are faked, so this runs without ROS."""

import importlib
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest


class FakeNode:
    def __init__(self, name):
        self.params = {}
        self.logger = MagicMock()

    def declare_parameter(self, name, value):
        self.params[name] = value

    def get_parameter(self, name):
        return SimpleNamespace(value=self.params[name])

    def get_logger(self):
        return self.logger

    def create_publisher(self, *args):
        return MagicMock()

    def create_subscription(self, *args, **kwargs):
        return MagicMock()


class FakeBridge:
    used = []

    def imgmsg_to_cv2(self, msg, desired_encoding):
        self.used.append(desired_encoding)
        return "frame"


def fake_cv2():
    return SimpleNamespace(
        COLOR_RGB2BGR="rgb to bgr",
        COLOR_GRAY2BGR="gray to bgr",
        COLOR_YUV2BGR_YUY2="yuy2 to bgr",
        IMWRITE_JPEG_QUALITY=1,
        cvtColor=MagicMock(return_value="converted"),
        imencode=MagicMock(return_value=(True, SimpleNamespace(tobytes=lambda: b"jpeg"))),
    )


@pytest.fixture
def node(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "1")
    for name in ("rclpy", "rclpy.qos", "sensor_msgs", "sensor_msgs.msg",
                 "std_msgs", "std_msgs.msg"):
        monkeypatch.setitem(sys.modules, name, MagicMock())
    monkeypatch.setitem(sys.modules, "rclpy.node", SimpleNamespace(Node=FakeNode))
    monkeypatch.setitem(sys.modules, "rclpy.serialization",
                        SimpleNamespace(deserialize_message=lambda raw, _: raw))
    monkeypatch.setitem(sys.modules, "cv_bridge", None)  # None: importing it raises
    monkeypatch.setitem(sys.modules, "cv2", fake_cv2())
    monkeypatch.delitem(sys.modules, "telegram_alert.telegram_node", raising=False)
    FakeBridge.used = []
    yield importlib.import_module("telegram_alert.telegram_node").TelegramNode()
    sys.modules.pop("telegram_alert.telegram_node", None)


def working_bridge(monkeypatch):
    monkeypatch.setitem(sys.modules, "cv_bridge", SimpleNamespace(CvBridge=FakeBridge))


def frame(node, encoding="bgr8"):
    node._last_image = (SimpleNamespace(encoding=encoding), 0.0)


def test_node_starts_without_cv_bridge(node):
    assert node.bot is not None


def test_no_cv_bridge_sends_the_alert_as_text(node):
    frame(node)
    assert node.snapshot() == (None, "(camera image failed)")


def test_no_cv2_sends_the_alert_as_text(node, monkeypatch):
    working_bridge(monkeypatch)
    monkeypatch.setitem(sys.modules, "cv2", None)
    frame(node)
    assert node.snapshot() == (None, "(camera image failed)")


def test_unknown_encoding_sends_the_alert_as_text(node, monkeypatch):
    working_bridge(monkeypatch)
    frame(node, "bayer_rggb8")
    assert node.snapshot() == (None, "(camera image failed)")


def test_failed_jpeg_sends_the_alert_as_text(node, monkeypatch):
    working_bridge(monkeypatch)
    sys.modules["cv2"].imencode.return_value = (False, None)
    frame(node)
    assert node.snapshot() == (None, "(camera image failed)")


@pytest.mark.parametrize("encoding, code", [
    ("rgb8", "rgb to bgr"),
    ("mono8", "gray to bgr"),
    ("yuv422_yuy2", "yuy2 to bgr"),
])
def test_cv2_converts_the_colours(node, monkeypatch, encoding, code):
    working_bridge(monkeypatch)
    frame(node, encoding)
    assert node.snapshot()[0] == b"jpeg"
    sys.modules["cv2"].cvtColor.assert_called_once_with("frame", code)


def test_bgr_frames_are_not_converted(node, monkeypatch):
    working_bridge(monkeypatch)
    frame(node)
    assert node.snapshot()[0] == b"jpeg"
    sys.modules["cv2"].cvtColor.assert_not_called()


def test_cv_bridge_never_converts_colours(node, monkeypatch):
    # Its cvtColor2 segfaults under NumPy 2, and no except can catch that.
    working_bridge(monkeypatch)
    for encoding in ("bgr8", "rgb8", "mono8", "yuv422_yuy2"):
        frame(node, encoding)
        node.snapshot()
    assert set(FakeBridge.used) == {"passthrough"}


def test_recordings_go_with_the_next_alert_and_are_deleted(node, monkeypatch, tmp_path):
    # D32: password_node saves the failed answers and sends their paths
    from telegram_alert import voice
    monkeypatch.setattr(voice, "to_voice", lambda wav: ("voice", b"ogg:" + wav))
    paths = []
    for i in (1, 2):
        path = tmp_path / ("%d.wav" % i)
        path.write_bytes(b"wav%d" % i)
        paths.append(path)
        node.on_recording(SimpleNamespace(data=str(path)))
    node.on_recording(SimpleNamespace(data=str(tmp_path / "gone.wav")))  # skipped
    assert node.take_recordings() == [("voice", b"ogg:wav1"), ("voice", b"ogg:wav2")]
    assert not any(p.exists() for p in paths)
    assert node.take_recordings() == []  # used once
