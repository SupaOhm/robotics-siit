"""ROS 2 node: classify what is in front of the robot, on request.

Topics (all standard messages, D1):
  sub  /detect/request  String  request id from the state machine
  sub  <image_topic>    Image   camera frames, ignored unless a request waits
  pub  /detect/result   String  JSON {id, kind, label, confidence, clip}

YOLO runs on the first frame after a request, so it never sees an old view
from before the robot stopped. If there is no frame, or YOLO fails, there is
no reply: the state machine retries, then treats it as a person (D7). Replying
"unknown" here could let a person skip the password.
"""

import json

import rclpy
from cv_bridge import CvBridge
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy
from sensor_msgs.msg import Image
from std_msgs.msg import String

from .classifier import classify, parse_name_table
from .yolo_backend import YoloDetector


class DetectorNode(Node):
    def __init__(self):
        super().__init__("detector_node")
        p = self.declare_parameter
        p("model_path", "yolo11n_ncnn_model")
        p("image_size", 320)
        p("person_threshold", 0.25)
        p("object_threshold", 0.5)
        p("name_table", ["chair=chair", "dining table=table", "bottle=bottle"])
        p("image_topic", "/camera/image_raw")
        p("frame_timeout", 2.0)

        g = lambda name: self.get_parameter(name).value
        self.person_threshold = float(g("person_threshold"))
        self.object_threshold = float(g("object_threshold"))
        self.names = parse_name_table(g("name_table"))
        self.frame_timeout = float(g("frame_timeout"))
        self.detector = YoloDetector(
            g("model_path"), int(g("image_size")),
            min(self.person_threshold, self.object_threshold))
        self.bridge = CvBridge()
        self.pending_id = None
        self.requested_at = 0.0

        self.result_pub = self.create_publisher(String, "/detect/result", 10)
        self.create_subscription(String, "/detect/request", self.on_request, 10)
        # Depth 1: frames that arrive during a slow inference are dropped.
        self.create_subscription(
            Image, g("image_topic"), self.on_image,
            QoSProfile(depth=1, reliability=ReliabilityPolicy.BEST_EFFORT))
        self.create_timer(0.5, self.on_tick)
        self.get_logger().info("detector_node ready (%d names, topic %s)"
                               % (len(self.names), g("image_topic")))

    def now(self) -> float:
        return self.get_clock().now().nanoseconds / 1e9

    def on_request(self, msg) -> None:
        self.pending_id = msg.data
        self.requested_at = self.now()

    def on_image(self, msg) -> None:
        if self.pending_id is None:
            return
        request_id, self.pending_id = self.pending_id, None
        try:
            frame = self.bridge.imgmsg_to_cv2(msg, desired_encoding="bgr8")
            detections = self.detector.detect(frame)
        except Exception as error:
            self.get_logger().error("request %s failed: %s" % (request_id, error))
            return
        result = classify(request_id, detections, self.names,
                          self.person_threshold, self.object_threshold)
        self.result_pub.publish(String(data=json.dumps(result)))
        self.get_logger().info("result: %s" % json.dumps(result))

    def on_tick(self) -> None:
        if (self.pending_id is not None
                and self.now() - self.requested_at > self.frame_timeout):
            self.get_logger().warning("request %s: no camera frame, not replying"
                                      % self.pending_id)
            self.pending_id = None


def main(args=None):
    rclpy.init(args=args)
    node = DetectorNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
