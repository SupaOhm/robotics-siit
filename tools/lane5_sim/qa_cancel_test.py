import time
import rclpy
from std_msgs.msg import Empty, String
from geometry_msgs.msg import Twist

rclpy.init()
node = rclpy.create_node("lane5_qa_cancel_test")

start_pub = node.create_publisher(Empty, "/avoidance/start", 10)
cancel_pub = node.create_publisher(Empty, "/avoidance/cancel", 10)

turn_started = [None]
result = [None]

def on_cmd(msg):
    if abs(msg.angular.z) > 0.01 and turn_started[0] is None:
        turn_started[0] = time.monotonic()
        print("[TURN] Robot received rotation command", flush=True)

def on_result(msg):
    result[0] = msg.data
    print("[RESULT]", msg.data, flush=True)

node.create_subscription(Twist, "/avoidance/cmd_vel", on_cmd, 10)
node.create_subscription(String, "/avoidance/result", on_result, 10)

try:
    print("[READY] Waiting for Lane 3 connections", flush=True)
    deadline = time.monotonic() + 5.0

    while start_pub.get_subscription_count() == 0 or cancel_pub.get_subscription_count() == 0:
        rclpy.spin_once(node, timeout_sec=0.05)
        if time.monotonic() > deadline:
            raise RuntimeError("Lane 3 start/cancel subscriber not found")

    start_pub.publish(Empty())
    print("[START] Avoidance requested", flush=True)

    cancel_sent = False
    deadline = time.monotonic() + 5.0

    while time.monotonic() < deadline and result[0] is None:
        rclpy.spin_once(node, timeout_sec=0.02)

        if turn_started[0] is not None and not cancel_sent:
            if time.monotonic() - turn_started[0] >= 0.35:
                cancel_pub.publish(Empty())
                cancel_sent = True
                print("[CANCEL] Cancel requested during rotation", flush=True)

    if result[0] is None:
        print("[TIMEOUT] No avoidance result received", flush=True)
        cancel_pub.publish(Empty())

    print("[FINAL]", result[0], flush=True)

finally:
    node.destroy_node()
    rclpy.shutdown()
