"""ROS 2 node: Telegram alerts for the security checkpoint.

Follows docs/interfaces.md (contract v0.3, D11, D14, D15, D26):
  sub  /telegram/alert     String  alert id: send a photo with Allow / Deny
  sub  /telegram/blocking  String  new alert id: Deny or 30 s timeout happened;
                                   expire Allow / Deny, send Resume
  sub  <image_topic>       Image   latest camera frame, used for the photo
  pub  /telegram/decision  String  JSON {"id": "a3", "decision": "allow"|"deny"|"resume"}

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
from sensor_msgs.msg import Image
from std_msgs.msg import String

from .bot import AlertBot
from .settings import load_settings


class TelegramNode(Node):
    def __init__(self):
        super().__init__("telegram_node")
        p = self.declare_parameter
        p("image_topic", "/camera/image_raw")
        p("jpeg_quality", 85)
        p("max_image_age", 2.0)  # older frames are still sent, with a note
        p("env_file", "")  # optional .env with TELEGRAM_* (gitignored)

        g = lambda name: self.get_parameter(name).value
        settings = load_settings(env_file=g("env_file"))
        self.jpeg_quality = int(g("jpeg_quality"))
        self.max_image_age = float(g("max_image_age"))

        from cv_bridge import CvBridge
        self.bridge = CvBridge()
        self._last_image = None  # (Image msg, monotonic time received)
        self.loop = None

        self.decision_pub = self.create_publisher(String, "/telegram/decision", 10)
        self.create_subscription(String, "/telegram/alert", self.on_alert, 10)
        self.create_subscription(String, "/telegram/blocking", self.on_blocking, 10)
        self.create_subscription(Image, g("image_topic"), self.on_image,
                                 qos_profile_sensor_data)
        self.bot = AlertBot(settings, self.publish_decision, log=self.get_logger().info)

    def publish_decision(self, decision: dict) -> None:
        self.decision_pub.publish(String(data=json.dumps(decision)))

    def on_image(self, msg) -> None:
        self._last_image = (msg, time.monotonic())  # converted only when needed

    def snapshot(self):
        """(jpeg bytes or None, note for the caption)."""
        if self._last_image is None:
            return None, "(no camera image)"
        msg, received = self._last_image
        try:
            import cv2
            frame = self.bridge.imgmsg_to_cv2(msg, desired_encoding="bgr8")
            ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, self.jpeg_quality])
        except Exception as e:  # bad encoding etc.: still send the alert
            self.get_logger().error("camera frame to JPEG failed: %s" % e)
            return None, "(camera image failed)"
        if not ok:
            return None, "(camera image failed)"
        age = time.monotonic() - received
        note = "(camera image %.0f s old)" % age if age > self.max_image_age else ""
        return buf.tobytes(), note

    def submit(self, coro) -> None:
        if self.loop is None:
            self.get_logger().warning("Telegram bot not running yet, message dropped")
            coro.close()
            return
        asyncio.run_coroutine_threadsafe(coro, self.loop)

    def on_alert(self, msg) -> None:
        alert_id = msg.data.strip()
        if not alert_id:
            self.get_logger().warning("empty alert id ignored")
            return
        jpeg, note = self.snapshot()
        self.get_logger().info("alert %s (photo: %s)" % (alert_id, "yes" if jpeg else "no"))
        self.submit(self.bot.alert(alert_id, jpeg, note))

    def on_blocking(self, msg) -> None:
        alert_id = msg.data.strip()
        if not alert_id:
            self.get_logger().warning("empty blocking id ignored")
            return
        self.get_logger().info("blocking %s" % alert_id)
        self.submit(self.bot.blocking(alert_id))

    async def run(self) -> None:
        await self.bot.start()
        self.loop = asyncio.get_running_loop()
        try:
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
