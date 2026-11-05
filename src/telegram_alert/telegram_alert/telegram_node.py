"""ROS 2 node: Telegram alerts for the security checkpoint.

Follows docs/interfaces.md (contract v0.3, D11, D14, D15, D26):
  sub  /telegram/alert     String  alert id: play the countdown, then send a photo
                                   with Allow / Deny
  sub  /telegram/blocking  String  new alert id: Deny or 30 s timeout happened;
                                   expire Allow / Deny, send Resume
  sub  /robot/state        String  leaving WAIT_OPERATOR / BLOCKING closes old buttons
  sub  <image_topic>       Image   latest camera frame, used for the photo
  pub  /telegram/decision  String  JSON {"id": "a3", "decision": "allow"|"deny"|"resume"}
  pub  /audio/play         String  photo_countdown

The 30 s timeout is in the state machine; this node only shows it.
ROS spins in a background thread; the Telegram bot runs on asyncio in the
main thread. ROS callbacks hand work to the bot with run_coroutine_threadsafe.
"""

import asyncio
import json
import threading
import time

import rclpy
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from rclpy.serialization import deserialize_message
from sensor_msgs.msg import Image
from std_msgs.msg import String

from .bot import AlertBot
from .settings import load_settings

MAX_PENDING = 10  # messages kept while the bot is still connecting
COUNTDOWN_CLIP = "photo_countdown"
# Camera encoding -> cv2 colour conversion to BGR. Not cv_bridge's own: under
# NumPy 2 it segfaults, which no except can catch, and the alert dies with the node.
TO_BGR = {
    "bgr8": None,
    "rgb8": "COLOR_RGB2BGR",
    "mono8": "COLOR_GRAY2BGR",
    "yuv422_yuy2": "COLOR_YUV2BGR_YUY2",
}


class TelegramNode(Node):
    def __init__(self):
        super().__init__("telegram_node")
        p = self.declare_parameter
        p("image_topic", "/camera/image_raw")
        p("jpeg_quality", 85)
        p("max_image_age", 2.0)  # older frames are still sent, with a note
        p("operator_timeout", 30)  # the state machine's WAIT_OPERATOR timeout (text only)
        p("photo_delay", 9.0)  # /telegram/alert to photo: password_denied + countdown clip
        p("env_file", "")  # optional .env with TELEGRAM_* (gitignored)

        g = lambda name: self.get_parameter(name).value
        settings = load_settings(env_file=g("env_file"))
        self.jpeg_quality = int(g("jpeg_quality"))
        self.max_image_age = float(g("max_image_age"))
        self.photo_delay = float(g("photo_delay"))

        self._last_image = None  # (serialized Image bytes, monotonic time received)
        self._robot_state = None
        self.loop = None
        self._pending = []  # coroutine factories waiting for the bot to connect
        self._pending_lock = threading.Lock()
        self._waiting_alert = None  # alert id in its countdown, sent when the timer ends
        self._alert_lock = threading.Lock()

        self.decision_pub = self.create_publisher(String, "/telegram/decision", 10)
        self.audio_pub = self.create_publisher(String, "/audio/play", 10)
        self.create_subscription(String, "/telegram/alert", self.on_alert, 10)
        self.create_subscription(String, "/telegram/blocking", self.on_blocking, 10)
        self.create_subscription(String, "/robot/state", self.on_robot_state, 10)
        # raw=True: keep the bytes and only deserialize the frame an alert needs
        self.create_subscription(Image, g("image_topic"), self.on_image,
                                 qos_profile_sensor_data, raw=True)
        log = self.get_logger()
        # The card goes out after the countdown, so it shows the time left.
        time_left = max(int(g("operator_timeout") - self.photo_delay), 1)
        self.bot = AlertBot(settings, self.publish_decision, log=log.info,
                            warn=log.warning, timeout_s=time_left)

    def publish_decision(self, decision: dict) -> None:
        self.decision_pub.publish(String(data=json.dumps(decision)))

    def on_image(self, raw: bytes) -> None:
        self._last_image = (raw, time.monotonic())

    def snapshot(self):
        """(jpeg bytes or None, note for the caption)."""
        if self._last_image is None:
            return None, "(no camera image)"
        raw, received = self._last_image
        try:
            # Imported here so a broken cv_bridge or cv2 costs the photo, not the alert.
            import cv2
            from cv_bridge import CvBridge
            msg = deserialize_message(raw, Image)
            conversion = TO_BGR[msg.encoding]
            frame = CvBridge().imgmsg_to_cv2(msg, desired_encoding="passthrough")
            if conversion is not None:
                frame = cv2.cvtColor(frame, getattr(cv2, conversion))
            ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, self.jpeg_quality])
        except Exception as e:  # unknown encoding etc.: still send the alert
            self.get_logger().error("camera frame to JPEG failed: %s" % e)
            return None, "(camera image failed)"
        if not ok:
            return None, "(camera image failed)"
        age = time.monotonic() - received
        note = "(camera image %.0f s old)" % age if age > self.max_image_age else ""
        return buf.tobytes(), note

    def submit(self, make_coro) -> None:
        """Run ``make_coro()`` on the bot's loop; queue it while connecting."""
        with self._pending_lock:
            if self.loop is None:
                self._pending.append(make_coro)
                del self._pending[:-MAX_PENDING]
                self.get_logger().warning("Telegram not connected yet, message queued")
                return
        future = asyncio.run_coroutine_threadsafe(make_coro(), self.loop)
        future.add_done_callback(self._log_failure)

    def _log_failure(self, future) -> None:
        if not future.cancelled() and future.exception() is not None:
            self.get_logger().error("Telegram task failed: %r" % future.exception())

    def on_alert(self, msg) -> None:
        alert_id = msg.data.strip()
        if not alert_id:
            self.get_logger().warning("empty alert id ignored")
            return
        with self._alert_lock:
            self._waiting_alert = alert_id
        self.audio_pub.publish(String(data=COUNTDOWN_CLIP))
        timer = threading.Timer(self.photo_delay, self.send_alert, args=(alert_id,))
        timer.daemon = True
        timer.start()

    def send_alert(self, alert_id: str) -> None:
        """The countdown ended: take the photo, unless the robot moved on."""
        jpeg, note = self.snapshot()
        with self._alert_lock:
            if self._waiting_alert != alert_id:
                self.get_logger().info("alert %s skipped: the robot moved on" % alert_id)
                return
            self._waiting_alert = None
            self.get_logger().info("alert %s (photo: %s)" % (alert_id, "yes" if jpeg else "no"))
            self.submit(lambda: self.bot.alert(alert_id, jpeg, note))

    def on_blocking(self, msg) -> None:
        alert_id = msg.data.strip()
        if not alert_id:
            self.get_logger().warning("empty blocking id ignored")
            return
        self.get_logger().info("blocking %s" % alert_id)
        self.submit(lambda: self.bot.blocking(alert_id))

    def on_robot_state(self, msg) -> None:
        new, old = msg.data.strip(), self._robot_state
        self._robot_state = new
        if old is not None and new != old:
            with self._alert_lock:
                if old == "WAIT_OPERATOR":
                    self._waiting_alert = None  # no card for a person we left
                self.submit(lambda: self.bot.robot_state(old, new))

    async def connect(self) -> None:
        """Keep trying until Telegram answers: the hotspot may come up after
        the robot boots (D17). A wrong token is fatal."""
        from telegram.error import InvalidToken
        delay = 2.0
        while True:
            try:
                await self.bot.start()
                return
            except InvalidToken:
                raise
            except Exception as e:
                self.get_logger().warning(
                    "Telegram not reachable (%r), retrying in %.0f s" % (e, delay))
                try:
                    await self.bot.stop()
                except Exception:
                    pass
                await asyncio.sleep(delay)
                delay = min(delay * 2, 60.0)

    async def run(self) -> None:
        try:
            await self.connect()
            with self._pending_lock:
                self.loop = asyncio.get_running_loop()
                # Tasks start in this order, ahead of anything submitted later.
                for make_coro in self._pending:
                    self.loop.create_task(make_coro()).add_done_callback(self._log_failure)
                self._pending = []
            await asyncio.Event().wait()  # until Ctrl+C cancels us
        finally:
            await self.bot.stop()


def main(args=None):
    rclpy.init(args=args)
    node = TelegramNode()
    threading.Thread(target=rclpy.spin, args=(node,), daemon=True).start()
    try:
        asyncio.run(node.run())
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
