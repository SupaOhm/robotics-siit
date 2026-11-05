
from pathlib import Path

import rclpy
from rclpy.node import Node
from std_msgs.msg import String
from rcl_interfaces.msg import ParameterDescriptor
from ament_index_python.packages import get_package_share_directory

from .player_core import AudioPlayer


class AudioNode(Node):
    def __init__(self):
        super().__init__("audio_node")

        self.declare_parameter(
            "cooldown_seconds",
            5.0,
            descriptor=ParameterDescriptor(dynamic_typing=True),
        )

        clip_dir = (
            Path(get_package_share_directory("audio_player"))
            / "clips"
        )

        # /audio/done: a clip finished playing, e.g. password_node's
        # countdown, so it opens the mic right after it (D33)
        self.done_pub = self.create_publisher(String, "/audio/done", 10)

        self.player = AudioPlayer(
            cooldown=float(self.get_parameter("cooldown_seconds").value),
            clip_dir=clip_dir,
            logger=self.get_logger(),
            on_done=lambda clip_id: self.done_pub.publish(String(data=clip_id)),
        )

        self.subscription = self.create_subscription(
            String,
            "/audio/play",
            self.on_audio_request,
            10,
        )

        self.get_logger().info("Audio node ready")

    def on_audio_request(self, msg):
        if not self.player.request(msg.data):
            self.get_logger().warning(
                f"Clip rejected or on cooldown: {msg.data}"
            )

    def destroy_node(self):
        self.player.close()
        return super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    node = AudioNode()

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
