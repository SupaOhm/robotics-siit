
import math

import rclpy
from rclpy.node import Node
from sensor_msgs.msg import LaserScan
from coppeliasim_zmqremoteapi_client import RemoteAPIClient


class ScanBridge(Node):

    def __init__(self):
        super().__init__("lane5_scan_bridge")

        # Connect to CoppeliaSim on Windows
        self.client = RemoteAPIClient(
            "host.docker.internal", 23000
        )
        self.sim = self.client.require("sim")

        # Publish LiDAR data to ROS 2
        self.publisher = self.create_publisher(
            LaserScan,
            "/scan",
            10
        )

        # SickS300 scanning settings
        self.angle_min = math.radians(-135.0)
        self.angle_max = math.radians(135.0)
        self.angle_increment = math.radians(1.0)

        self.range_min = 0.05
        self.range_max = 5.0

        # 271 beams from -135 to +135 degrees
        self.num_beams = 271

        # Publish approximately 5 times per second
        self.scan_period = 0.2
        self.timer = self.create_timer(
            self.scan_period,
            self.publish_scan
        )

        self.first_scan_logged = False

        self.get_logger().info(
            "Connected to CoppeliaSim!"
        )
        self.get_logger().info(
            "Waiting for SickS300 data..."
        )

    def publish_scan(self):

        # Do not publish while simulation is stopped
        if (
            self.sim.getSimulationState()
            == self.sim.simulation_stopped
        ):
            return

        # Read XYZ points from the Lua signal
        data = self.sim.getBufferProperty(
            self.sim.handle_scene,
            "signal.lane5_scan_xyz",
            {"noError": True}
        )

        if not data:
            return

        points = self.sim.unpackFloatTable(data)

        if len(points) < 3:
            return

        # Prepare a LaserScan message
        msg = LaserScan()

        msg.header.stamp = (
            self.get_clock().now().to_msg()
        )
        msg.header.frame_id = "sick_s300"

        msg.angle_min = self.angle_min
        msg.angle_max = self.angle_max
        msg.angle_increment = self.angle_increment

        msg.time_increment = 0.0
        msg.scan_time = self.scan_period

        msg.range_min = self.range_min
        msg.range_max = self.range_max

        # Infinity means no detected point in this bin
        ranges = [float("inf")] * self.num_beams

        # Convert XYZ points into distance by angle
        for i in range(0, len(points) - 2, 3):

            x = points[i]
            y = points[i + 1]

            distance = math.hypot(x, y)
            angle = math.atan2(y, x)

            if not (
                self.range_min
                <= distance
                <= self.range_max
            ):
                continue

            if not (
                self.angle_min
                <= angle
                <= self.angle_max
            ):
                continue

            index = round(
                (angle - self.angle_min)
                / self.angle_increment
            )

            if 0 <= index < self.num_beams:
                ranges[index] = min(
                    ranges[index],
                    distance
                )

        msg.ranges = ranges

        # Intensity is not provided by this sensor
        msg.intensities = []

        # Publish to ROS 2
        self.publisher.publish(msg)

        if not self.first_scan_logged:
            detected = sum(
                math.isfinite(r) for r in ranges
            )

            self.get_logger().info(
                f"Published /scan: "
                f"{self.num_beams} beams, "
                f"{detected} bins with detections"
            )

            self.first_scan_logged = True


def main():
    rclpy.init()
    node = None

    try:
        node = ScanBridge()
        rclpy.spin(node)

    except KeyboardInterrupt:
        pass

    finally:
        if node is not None:
            node.destroy_node()

        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
