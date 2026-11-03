import time
import rclpy
from geometry_msgs.msg import Twist

rclpy.init()
node = rclpy.create_node("lane5_qa_avoidance_relay")
publisher = node.create_publisher(Twist, "/cmd_vel", 10)
last_command = [0.0]
active = [False]

def forward(msg):
    cmd = Twist()
    cmd.angular.z = max(-1.0, min(1.0, float(msg.angular.z)))
    publisher.publish(cmd)
    last_command[0] = time.monotonic()
    active[0] = True

def watchdog():
    if active[0] and time.monotonic() - last_command[0] > 0.5:
        publisher.publish(Twist())
        active[0] = False

node.create_subscription(Twist, "/avoidance/cmd_vel", forward, 10)
node.create_timer(0.1, watchdog)

print("QA avoidance relay ready", flush=True)
try:
    rclpy.spin(node)
finally:
    publisher.publish(Twist())
    node.destroy_node()
    rclpy.shutdown()
