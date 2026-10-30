"""ROS 2 node: spoken-password check for the security checkpoint.

Topics (all std_msgs, so no custom message package is needed):
  sub  /password/start   Empty   begin a session (main state machine, person seen)
  sub  /password/cancel  Empty   abort the session (e.g. person walked away)
  sub  /password/text    String  one attempt as text, input_mode == "topic_only"
                                 (simulation / testing; "" = nobody spoke)
  pub  /password/result  String  "granted" | "denied" | "cancelled"  (once per session)
  pub  /password/event   String  JSON progress events for audio / UI

In "mic" mode a worker thread runs the listen -> transcribe -> check loop,
waiting ``listen_delay`` seconds before each attempt so the robot's own
prompt clip is not recorded.
"""

import json
import threading

import rclpy
from rclpy.node import Node
from std_msgs.msg import Empty, String

from .verifier import EventType, PasswordVerifier

RESULT_FOR_EVENT = {
    EventType.GRANTED: "granted",
    EventType.LOCKED_OUT: "denied",
    EventType.CANCELLED: "cancelled",
}


class PasswordNode(Node):
    def __init__(self):
        super().__init__("password_node")
        p = self.declare_parameter
        p("password_hash", "")
        p("salt", "")
        p("password_chars", 4)
        p("max_attempts", 3)
        p("match_mode", "contains")  # contains | exact
        p("max_service_errors", 3)
        p("input_mode", "mic")  # mic | topic_only
        p("engine", "google")  # google | vosk
        p("language", "en-US")
        p("mic_device_index", -1)  # -1 = system default microphone
        p("vosk_model_path", "")
        p("listen_delay", 2.5)
        p("listen_timeout", 6.0)
        p("phrase_time_limit", 5.0)
        p("log_transcripts", False)  # only for tuning: prints what was heard

        g = lambda name: self.get_parameter(name).value
        if not g("password_hash") or not g("salt"):
            raise RuntimeError("password_hash and salt must be set (see make_password_hash)")

        self.verifier = PasswordVerifier(
            password_hash=g("password_hash"),
            salt=g("salt"),
            password_chars=int(g("password_chars")),
            max_attempts=int(g("max_attempts")),
            match_mode=g("match_mode"),
            max_service_errors=int(g("max_service_errors")),
        )
        self.listen_delay = float(g("listen_delay"))
        self.log_transcripts = bool(g("log_transcripts"))
        self.lock = threading.Lock()
        self._cancel = threading.Event()
        self._worker = None

        self.result_pub = self.create_publisher(String, "/password/result", 10)
        self.event_pub = self.create_publisher(String, "/password/event", 10)
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
        elif self.mode == "topic_only":
            self.create_subscription(String, "/password/text", self.on_text, 10)
        else:
            raise RuntimeError("unknown input_mode: %s" % self.mode)

        self.get_logger().info(
            "password_node ready (mode=%s, engine=%s, language=%s, attempts=%d)"
            % (self.mode, g("engine"), g("language"), self.verifier.max_attempts))

    def publish(self, events) -> None:
        for ev in events:
            self.event_pub.publish(String(data=json.dumps(ev.to_dict())))
            self.get_logger().info("event: %s (attempts left %d)"
                                   % (ev.type.value, ev.attempts_left))
            if ev.type in RESULT_FOR_EVENT:
                self.result_pub.publish(String(data=RESULT_FOR_EVENT[ev.type]))

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

    def on_text(self, msg) -> None:
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
                self.publish(self.verifier.listening())

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
                    if self.log_transcripts:
                        self.get_logger().info("heard: %s" % result.candidates)
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
