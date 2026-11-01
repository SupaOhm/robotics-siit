"""ROS 2 node: spoken-password check for the security checkpoint.

Follows docs/interfaces.md (contract v0.3, D9, D23, D24, D27):
  sub  /password/start      Empty   begin a session (person found), 3 attempts
  sub  /password/cancel     Empty   abort (operator took over / person left)
  sub  /password/sim_input  String  one typed attempt, input_mode == "sim" only
                                    ("" = nobody spoke)
  pub  /password/result     String  "granted" | "denied" | "cancelled", once per session
  pub  /audio/play          String  password_prompt / password_wrong / password_denied

The password is not in the repo: ROBOT_PASSWORD_HASH (printed by
make_password_hash) comes from the environment unless the parameter is set.
What the person says is never published or logged.

In "mic" mode a worker thread runs the listen -> transcribe -> check loop,
waiting ``listen_delay`` seconds before each attempt so the robot's own
prompt clip is not recorded.
"""

import os
import threading

import rclpy
from rclpy.node import Node
from std_msgs.msg import Empty, String

from .verifier import PasswordVerifier, outputs_for, parse_stored


class PasswordNode(Node):
    def __init__(self):
        super().__init__("password_node")
        p = self.declare_parameter
        p("password_hash", "")  # empty -> ROBOT_PASSWORD_HASH
        p("max_attempts", 3)
        p("match_mode", "exact")  # exact | contains
        p("max_service_errors", 3)
        p("input_mode", "mic")  # mic | sim
        p("engine", "vosk")  # vosk | google
        p("language", "en-US")
        p("mic_device_index", -1)  # -1 = system default microphone
        p("vosk_model_path", "")
        p("listen_delay", 2.5)
        p("listen_timeout", 6.0)
        p("phrase_time_limit", 5.0)
        p("operation_timeout", 10.0)
        p("sim_timeout", 8.5)  # sim: no typed attempt this long -> silence; 0 = off

        g = lambda name: self.get_parameter(name).value
        stored = g("password_hash") or os.environ.get("ROBOT_PASSWORD_HASH", "")
        if not stored:
            raise RuntimeError(
                "No password set. Run `ros2 run password_system make_password_hash "
                "<digits>` and export the ROBOT_PASSWORD_HASH line it prints.")
        password_hash, salt, chars = parse_stored(stored)

        self.verifier = PasswordVerifier(
            password_hash=password_hash,
            salt=salt,
            password_chars=chars,
            max_attempts=int(g("max_attempts")),
            match_mode=g("match_mode"),
            max_service_errors=int(g("max_service_errors")),
        )
        self.listen_delay = float(g("listen_delay"))
        # Longest a listen + transcription can take; used to wait for the
        # previous session's worker to let go of the microphone.
        self.max_listen = (float(g("listen_timeout")) + float(g("phrase_time_limit"))
                           + float(g("operation_timeout")) + 2.0)
        self.lock = threading.Lock()
        self._cancel = threading.Event()
        self._worker = None

        self.result_pub = self.create_publisher(String, "/password/result", 10)
        self.audio_pub = self.create_publisher(String, "/audio/play", 10)
        self.create_subscription(Empty, "/password/start", self.on_start, 10)
        self.create_subscription(Empty, "/password/cancel", self.on_cancel, 10)

        self.mode = g("input_mode")
        self.listener = None
        self.sim_timeout = float(g("sim_timeout"))
        self._sim_timer = None
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
                operation_timeout=float(g("operation_timeout")),
            )
            try:
                self.listener.calibrate()
            except Exception as e:
                # Keep running: each attempt reports a service error, and 3 in a
                # row end as "denied", so the operator still gets the alert.
                self.get_logger().error(
                    "microphone not available (%r); check mic_device_index" % e)
        elif self.mode == "sim":
            self.create_subscription(String, "/password/sim_input", self.on_sim_input, 10)
        else:
            raise RuntimeError("unknown input_mode: %s" % self.mode)

        self.get_logger().info(
            "password_node ready (mode=%s, engine=%s, attempts=%d, match=%s)"
            % (self.mode, g("engine"), self.verifier.max_attempts,
               self.verifier.match_mode))

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
            # One result per session: close the old one before starting again
            self.publish(self.verifier.cancel())
            started = self.verifier.start()
            if self.listener is None:
                self.publish(started)
                self._arm_sim_timer()
                return
        previous = self._worker
        self._worker = threading.Thread(
            target=self.run_session, args=(self._cancel, previous, started), daemon=True)
        self._worker.start()

    def on_cancel(self, _msg) -> None:
        with self.lock:
            self._cancel.set()
            self.publish(self.verifier.cancel())
            self._arm_sim_timer()

    def on_sim_input(self, msg) -> None:
        with self.lock:
            if msg.data.strip():
                self.publish(self.verifier.submit([msg.data]))
            else:
                self.publish(self.verifier.no_speech())
            self._arm_sim_timer()

    def _arm_sim_timer(self) -> None:
        """Sim only: restart the per-attempt timer, so silence costs an attempt
        as it does on the robot. Call with the lock held."""
        if self._sim_timer is not None:
            self._sim_timer.cancel()
            self.destroy_timer(self._sim_timer)
            self._sim_timer = None
        if self.sim_timeout > 0 and self.verifier.active:
            self._sim_timer = self.create_timer(self.sim_timeout, self.on_sim_timeout)

    def on_sim_timeout(self) -> None:
        with self.lock:
            self.publish(self.verifier.no_speech())
            self._arm_sim_timer()

    def run_session(self, cancel, previous, started) -> None:
        if previous is not None:
            # It holds the microphone until its listen ends.
            previous.join(timeout=self.max_listen)
            if previous.is_alive():
                self.get_logger().warning("previous listen still running")
        with self.lock:
            if cancel.is_set():
                return
            self.publish(started)  # prompt now that the mic is free

        while not cancel.wait(self.listen_delay):
            with self.lock:
                if cancel.is_set() or not self.verifier.active:
                    return

            try:
                result = self.listener.listen_once()
            except Exception as e:  # never let the session die silently
                from .speech import ListenResult
                result = ListenResult("error", error="listen failed: %r" % e)

            with self.lock:
                if cancel.is_set() or not self.verifier.active:
                    return
                if result.kind == "error":
                    self.get_logger().warning(result.error)
                self.publish(self.verifier.handle(result))
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
