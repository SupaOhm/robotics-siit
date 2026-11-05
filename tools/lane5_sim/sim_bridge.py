
import time

import rclpy
from rclpy.node import Node
from geometry_msgs.msg import Twist
from coppeliasim_zmqremoteapi_client import RemoteAPIClient


class SimBridge(Node):

    def __init__(self):
        super().__init__("lane5_sim_bridge")

        # ==========================================
        # 1. Connect to CoppeliaSim
        # ==========================================
        self.client = RemoteAPIClient(
            "host.docker.internal",
            23000
        )

        self.sim = self.client.require("sim")

        # Find the robot in CoppeliaSim
        self.robot = self.sim.getObject("/youBot")

        # ==========================================
        # 2. Get four wheel joints
        # ==========================================
        self.wheels = [
            self.sim.getObject("/youBot/rollingJoint_fl"),
            self.sim.getObject("/youBot/rollingJoint_rl"),
            self.sim.getObject("/youBot/rollingJoint_rr"),
            self.sim.getObject("/youBot/rollingJoint_fr"),
        ]

        # ==========================================
        # 3. Movement settings
        # ==========================================
        self.forward_gain = 5.0
        self.rotation_gain = 2.0

        # Limit wheel speed for testing
        self.max_wheel_speed = 3.0

        # Stop if no new command arrives
        self.command_timeout = 1.0
        self.last_command_time = None
        self.command_active = False

        # ==========================================
        # 4. Subscribe to ROS 2 /cmd_vel
        # ==========================================
        self.subscription = self.create_subscription(
            Twist,
            "/cmd_vel",
            self.on_cmd_vel,
            10
        )

        # Check for command timeout
        self.watchdog = self.create_timer(
            0.1,
            self.check_timeout
        )

        self.get_logger().info(
            "Connected to CoppeliaSim!"
        )

        self.get_logger().info(
            "Four wheel joints found!"
        )

        self.get_logger().info(
            "Waiting for /cmd_vel commands..."
        )

    # ==============================================
    # 5. Convert ROS commands to wheel speeds
    # ==============================================
    def set_motion(self, forward, rotation):

        # Forward movement
        f = forward * self.forward_gain

        # FIX: Reverse rotation direction
        # Positive angular.z should turn LEFT
        r = -rotation * self.rotation_gain

        # Wheel order:
        # Front Left, Rear Left, Rear Right, Front Right
        speeds = [
            -f - r,
            -f - r,
            -f + r,
            -f + r,
        ]

        # Limit wheel speeds
        speeds = [
            max(
                -self.max_wheel_speed,
                min(self.max_wheel_speed, speed)
            )
            for speed in speeds
        ]

        # Send commands to CoppeliaSim
        for wheel, speed in zip(self.wheels, speeds):
            self.sim.setJointTargetVelocity(
                wheel,
                speed
            )

    # ==============================================
    # 6. Receive movement command from ROS 2
    # ==============================================
    def on_cmd_vel(self, msg):

        forward = msg.linear.x
        rotation = msg.angular.z

        self.last_command_time = time.monotonic()
        self.command_active = True

        # Move the simulated robot
        self.set_motion(
            forward,
            rotation
        )

        self.get_logger().info(
            f"Received command: forward={forward:.2f}, "
            f"rotate={rotation:.2f}"
        )

    # ==============================================
    # 7. Safety timeout
    # ==============================================
    def check_timeout(self):

        if not self.command_active:
            return

        elapsed = (
            time.monotonic() - self.last_command_time
        )

        if elapsed > self.command_timeout:

            # Stop all wheels
            self.set_motion(0.0, 0.0)

            self.command_active = False

            self.get_logger().info(
                "Command timeout: robot stopped."
            )

    # ==============================================
    # 8. Stop robot safely
    # ==============================================
    def stop_wheels(self):
        self.set_motion(0.0, 0.0)


# ==============================================
# 9. Main program
# ==============================================
def main():

    rclpy.init()
    node = None

    try:
        node = SimBridge()
        rclpy.spin(node)

    except KeyboardInterrupt:
        pass

    finally:

        if node is not None:

            try:
                node.stop_wheels()

            except Exception as error:
                print("Could not stop wheels:", error)

            node.destroy_node()

        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
