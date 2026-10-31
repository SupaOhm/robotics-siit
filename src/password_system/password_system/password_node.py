"""ROS 2 node: spoken-password check for the security checkpoint.

Follows docs/interfaces.md (contract v0.3, D9, D23, D24, D27):
  sub  /password/start      Empty   begin a session (person found), 3 attempts
  sub  /password/cancel     Empty   abort (operator took over / person left)
  sub  /password/sim_input  String  one typed attempt, input_mode == "sim" only
                                    ("" = nobody spoke)
  pub  /password/result     String  "granted" | "denied" | "cancelled", once per session
  pub  /audio/play          String  password_prompt / password_wrong / password_denied

The password is not in the repo: the salted hash comes from the environment
(ROBOT_PASSWORD_SALT, ROBOT_PASSWORD_HASH, ROBOT_PASSWORD_CHARS, printed by
make_password_hash) unless the parameters are set. What the person says is
never published or logged.

In "mic" mode a worker thread runs the listen -> transcribe -> check loop,
waiting ``listen_delay`` seconds before each attempt so the robot's own
prompt clip is not recorded.
"""

import os
import threading

import rclpy
from rclpy.node import Node
from std_msgs.msg import Empty, String

from .verifier import PasswordVerifier, outputs_for


class PasswordNode(Node):
    def __init__(self):
        super().__init__("password_node")
        p = self.declare_parameter
        p("password_hash", "")  # empty -> ROBOT_PASSWORD_HASH
        p("salt", "")  # empty -> ROBOT_PASSWORD_SALT
        p("password_chars", 0)  # 0 -> ROBOT_PASSWORD_CHARS
        p("max_attempts", 3)
        p("match_mode", "contains")  # contains | exact
        p("max_service_errors", 3)
        p("input_mode", "mic")  # mic | sim
        p("engine", "vosk")  # vosk | google
        p("language", "en-US")
        p("mic_device_index", -1)  # -1 = system default microphone
        p("vosk_model_path", "")
        p("listen_delay", 2.5)
        p("listen_timeout", 6.0)
        p("phrase_time_limit", 5.0)

        g = lambda name: self.get_parameter(name).value
        password_hash = g("password_hash") or os.environ.get("ROBOT_PASSWORD_HASH", "")
        salt = g("salt") or os.environ.get("ROBOT_PASSWORD_SALT", "")
        chars = int(g("password_chars") or os.environ.get("ROBOT_PASSWORD_CHARS", 0))
        if not password_hash or not salt or chars < 1:
            raise RuntimeError(
                "No password set. Run `ros2 run password_system make_password_hash "
                "<digits>` and export the ROBOT_PASSWORD_* lines it prints.")

        self.verifier = PasswordVerifier(
            password_hash=password_hash,
            salt=salt,
            password_chars=chars,
            max_attempts=int(g("max_attempts")),
            match_mode=g("match_mode"),
            max_service_errors=int(g("max_service_errors")),
        )
        self.listen_delay = float(g("listen_delay"))
        self.lock = threading.Lock()
        self._cancel = threading.Event()
        self._worker = None

        self.result_pub = self.create_publisher(String, "/password/result", 10)
        self.audio_pub = self.create_publisher(String, "/audio/play", 10)
        self.create_subscription(Empty, "/password/start", self.on_start, 10)
        self.create_subscription(Empty, "/password/cancel", self.on_cancel, 10)

        self.mode = g("input_mode")
        self.listener = None
        if self.mode == "mic":
            from .speech import SpeechListener
            device = int(g("mic_device_index"))
            self.listener = SpeechListener(
                engine=g("engine"),
                language=g("language"),
                device_index=None if device < 0 else device,
                listen_timeout=float(g("listen_timeout")),
                phrase_time_limit=float(g("phrase_time_limit")),
                vosk_model_path=g("vosk_model_path"),
            )
        elif self.mode == "sim":
            self.create_subscription(String, "/password/sim_input", self.on_sim_input, 10)
        else:
            raise RuntimeError("unknown input_mode: %s" % self.mode)

        self.get_logger().info(
            "password_node ready (mode=%s, engine=%s, attempts=%d)"
            % (self.mode, g("engine"), self.verifier.max_attempts))

    def publish(self, events) -> None:
        for ev in events:
            self.get_logger().info("%s (attempts left %d)"
                                   % (ev.type.value, ev.attempts_left))
        results, clips = outputs_for(events)
        for clip in clips:
            self.audio_pub.publish(String(data=clip))
        for result in results:
            self.result_pub.publish(String(data=result))

    def on_start(self, _msg) -> None:
        with self.lock:
            self._cancel.set()  # stop any session still running
            self._cancel = threading.Event()
            self.publish(self.verifier.start())
        if self.listener is not None:
            previous = self._worker
            self._worker = threading.Thread(
                target=self.run_session, args=(self._cancel, previous), daemon=True)
            self._worker.start()

    def on_cancel(self, _msg) -> None:
        with self.lock:
            self._cancel.set()
            self.publish(self.verifier.cancel())

    def on_sim_input(self, msg) -> None:
        with self.lock:
            if msg.data.strip():
                self.publish(self.verifier.submit([msg.data]))
            else:
                self.publish(self.verifier.no_speech())

    def run_session(self, cancel, previous) -> None:
        if previous is not None:
            previous.join()  # it holds the microphone until its listen ends
        while not cancel.wait(self.listen_delay):
            with self.lock:
                if cancel.is_set() or not self.verifier.active:
                    return

            result = self.listener.listen_once()

            with self.lock:
                if cancel.is_set() or not self.verifier.active:
                    return
                if result.kind == "no_speech":
                    events = self.verifier.no_speech()
                elif result.kind == "error":
                    self.get_logger().warning(result.error)
                    events = self.verifier.service_error()
                else:
                    events = self.verifier.submit(result.candidates)
                self.publish(events)
                if not self.verifier.active:
                    return

    def destroy_node(self):
        self._cancel.set()
        super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    node = PasswordNode()
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
