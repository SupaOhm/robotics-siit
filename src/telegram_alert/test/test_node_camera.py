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


# ----- countdown before the photo ----------------------------------------


class FakeTimer:
    started = []

    def __init__(self, delay, function, args=()):
        self.delay, self.function, self.args = delay, function, args

    def start(self):
        self.started.append(self)

    def fire(self):
        self.function(*self.args)


@pytest.fixture
def waiting(node, monkeypatch):
    """(node, what it submitted to the bot); the timers fire by hand."""
    FakeTimer.started = []
    monkeypatch.setattr("threading.Timer", FakeTimer)
    submitted = []
    node.submit = submitted.append
    frame(node)
    working_bridge(monkeypatch)
    return node, submitted


def test_alert_plays_the_countdown_and_waits_for_the_photo(waiting):
    node, submitted = waiting
    node.on_alert(SimpleNamespace(data="a1"))
    sys.modules["std_msgs.msg"].String.assert_called_with(data="photo_countdown")
    assert node.audio_pub.publish.call_count == 1
    assert submitted == [] and FakeTimer.started[0].delay == 10.5
    FakeTimer.started[0].fire()
    assert len(submitted) == 1


def test_card_shows_the_time_left_after_the_countdown(node):
    assert node.bot.book.timeout_s == 19  # 30 s - 10.5 s


def test_robot_leaving_during_the_countdown_skips_the_card(waiting):
    node, submitted = waiting
    node.on_robot_state(SimpleNamespace(data="WAIT_OPERATOR"))
    node.on_alert(SimpleNamespace(data="a1"))
    node.on_robot_state(SimpleNamespace(data="DRIVE"))
    FakeTimer.started[0].fire()
    assert len(submitted) == 1  # only the robot_state close, no alert


def test_a_state_message_that_lags_the_alert_keeps_the_card(waiting):
    node, submitted = waiting
    node.on_robot_state(SimpleNamespace(data="CHECKPOINT"))
    node.on_alert(SimpleNamespace(data="a1"))
    node.on_robot_state(SimpleNamespace(data="WAIT_OPERATOR"))
    FakeTimer.started[0].fire()
    assert len(submitted) == 2  # the state change, then the alert


def test_a_newer_alert_replaces_one_still_counting_down(waiting):
    node, submitted = waiting
    node.on_alert(SimpleNamespace(data="a1"))
    node.on_alert(SimpleNamespace(data="a2"))
    for timer in FakeTimer.started:
        timer.fire()
    assert len(submitted) == 1


def test_retake_plays_the_countdown_then_sends_a_new_photo(waiting):
    node, submitted = waiting
    node.start_retake("card")
    assert node.audio_pub.publish.call_count == 1
    assert FakeTimer.started[0].delay == 7.0 and submitted == []
    FakeTimer.started[0].fire()
    assert len(submitted) == 1
