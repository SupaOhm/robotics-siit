"""ROS 2 node: hand gestures from the operator's laptop webcam -> drive words.

Follows docs/interfaces.md (contract v0.3, D3, D4, D11, D14):
  pub  /gesture/command  String  forward | back | left | right | stop | none

The word is published at a fixed ``publish_rate`` (10 Hz) from a timer,
every tick, whether or not it changed. The camera runs in a worker thread;
if it or MediaPipe stalls for ``stale_s``, the timer publishes ``none``.
``none`` is also published on shutdown. Words only: the state machine turns
them into speeds.

input_mode:
  camera    webcam + MediaPipe (needs the hand_landmarker.task model)
  keyboard  w/s/a/d/space/x in this terminal, for testing without a camera
            (use `ros2 run`, a launch file gives the node no terminal)
"""

import threading
import time

import rclpy
from rclpy.logging import get_logger
from rclpy.node import Node
from std_msgs.msg import String

from .classifier import ClassifierParams, GestureClassifier
from .command_source import GesturePipeline, LatestWord
from .smoother import WordSmoother

TOPIC = "/gesture/command"


class GestureNode(Node):
    def __init__(self):
        super().__init__("gesture_node")
        d = ClassifierParams()
        p = self.declare_parameter
        p("input_mode", "camera")  # camera | keyboard
        p("camera_index", 0)
        p("model_path", "~/models/hand_landmarker.task")
        p("publish_rate", 10.0)
        p("show_window", False)
        p("stale_s", 0.3)
        p("extend_ratio", d.extend_ratio)
        p("fist_max_fingers", d.fist_max_fingers)
        p("deadzone_radius", d.deadzone_radius)
        p("deadzone_hysteresis", d.deadzone_hysteresis)
        p("forward_half_angle", d.forward_half_angle)
        p("back_min_angle", d.back_min_angle)
        p("angle_hysteresis", d.angle_hysteresis)
        p("confirm_frames", 3)
        p("back_confirm_frames", 6)
        p("dropout_hold_s", 0.3)
        p("key_hold_s", 0.8)

        g = lambda name: self.get_parameter(name).value
        self.mode = g("input_mode")
        self.latest = LatestWord(float(g("stale_s")))
        self.clock = time.monotonic
        self._stop = threading.Event()
        self._worker = None
        self.keyboard = None
        self._last_logged = None

        self.pub = self.create_publisher(String, TOPIC, 10)

        if self.mode == "camera":
            params = ClassifierParams(
                extend_ratio=float(g("extend_ratio")),
                fist_max_fingers=int(g("fist_max_fingers")),
                deadzone_radius=float(g("deadzone_radius")),
                deadzone_hysteresis=float(g("deadzone_hysteresis")),
                forward_half_angle=float(g("forward_half_angle")),
                back_min_angle=float(g("back_min_angle")),
                angle_hysteresis=float(g("angle_hysteresis")),
            )
            self.pipeline = GesturePipeline(
                GestureClassifier(params),
                WordSmoother(int(g("confirm_frames")), int(g("back_confirm_frames")),
                             float(g("dropout_hold_s"))))
            self._worker = threading.Thread(
                target=self._run_camera,
                args=(int(g("camera_index")), g("model_path"), bool(g("show_window"))),
                daemon=True)
        elif self.mode == "keyboard":
            from .keyboard_source import HELP, KeyboardCommand
            self.keyboard = KeyboardCommand(float(g("key_hold_s")))
            self._worker = threading.Thread(target=self._run_keyboard, daemon=True)
            self.get_logger().info(HELP)
        else:
            raise RuntimeError("unknown input_mode: %s" % self.mode)

        rate = float(g("publish_rate"))
        if rate <= 0:
            raise RuntimeError("publish_rate must be > 0")
        self.create_timer(1.0 / rate, self.on_timer)
        self._worker.start()
        self.get_logger().info("gesture_node ready (mode=%s, %.1f Hz on %s)"
                               % (self.mode, rate, TOPIC))

    def current_word(self) -> str:
        now = self.clock()
        if self.keyboard is not None:
            if self._worker is None or not self._worker.is_alive():
                return "none"  # no key reader: never repeat the last key
            return self.keyboard.word(now)
        return self.latest.get(now)

    def on_timer(self) -> None:
        word = self.current_word()
        self.pub.publish(String(data=word))
        if word != self._last_logged:
            self.get_logger().info("word: %s" % word)
            self._last_logged = word

    def _run_camera(self, camera_index, model_path, show_window) -> None:
        from .camera_loop import run_camera
        log = self.get_logger()
        try:
            run_camera(self.pipeline, self.latest.set, self._stop,
                       camera_index=camera_index, model_path=model_path,
                       show_window=show_window, log=log.warning, clock=self.clock)
        except Exception as e:
            # Node stays up and keeps publishing "none" (the word goes stale).
            log.error("camera input stopped: %r. Publishing none." % e)

    def _run_keyboard(self) -> None:
        from .keyboard_source import read_keys
        try:
            read_keys(lambda ch: self.keyboard.press(ch, self.clock()), self._stop)
        except Exception as e:
            self.get_logger().error("keyboard input stopped: %r. Publishing none." % e)
        finally:
            self.keyboard.force_none(self.clock())

    def publish_none(self, times: int = 3) -> None:
        for _ in range(times):
            self.pub.publish(String(data="none"))

    def destroy_node(self):
        self._stop.set()
        if self._worker is not None:
            self._worker.join(timeout=2.0)
        super().destroy_node()


def _init(args):
    # Handle Ctrl+C ourselves so the context is still valid for the final "none".
    try:
        from rclpy.signals import SignalHandlerOptions
        rclpy.init(args=args, signal_handler_options=SignalHandlerOptions.NO)
    except (ImportError, TypeError):
        rclpy.init(args=args)


def main(args=None):
    _init(args)
    node = None
    try:
        node = GestureNode()
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    except Exception as e:
        if node is None:  # bad parameter or input mode: report it, then clean up
            get_logger("gesture_node").fatal(
                "gesture_node failed to start: %s" % e)
            raise SystemExit(1)
        raise
    finally:
        if node is not None:
            if rclpy.ok():
                try:
                    node.publish_none()
                except Exception:
                    pass
            node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
