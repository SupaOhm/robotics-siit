"""ROS 2 node: turns /camera/tilt into the Yahboom pan/tilt servo command (D31).

  sub  /camera/tilt  std_msgs/Int32                 tilt in Yahboom units (s2, 0-110)
  pub  /Servo        yahboomcar_msgs/ServoControl   s1 = pan, s2 = tilt

Only this node imports the Yahboom message, so the rest of the contract
stays standard messages. yahboomcar_msgs is in the robot's Yahboom
workspace: source it before running this node.
"""

import rclpy
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile
from std_msgs.msg import Int32

TILT_MAX = 110  # the Yahboom driver clamps s2 to 0-110


class CameraTiltNode(Node):
    def __init__(self):
        super().__init__("camera_tilt")
        from yahboomcar_msgs.msg import ServoControl  # only on the robot
        self.ServoControl = ServoControl
        self.pan = int(self.declare_parameter("pan", 90).value)
        self.pub = self.create_publisher(ServoControl, "/Servo", 10)
        # Latched like the state machine's publisher, so starting after it
        # still gets the current angle
        latched = QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL)
        self.create_subscription(Int32, "/camera/tilt", self.on_tilt, latched)
        self.get_logger().info("camera_tilt ready (pan %d)" % self.pan)

    def on_tilt(self, msg):
        tilt = max(0, min(TILT_MAX, msg.data))
        self.pub.publish(self.ServoControl(s1=self.pan, s2=tilt))
        self.get_logger().info("tilt %d" % tilt)


def main(args=None):
    rclpy.init(args=args)
    node = CameraTiltNode()
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
