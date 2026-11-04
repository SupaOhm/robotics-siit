"""Security robot state machine (ROS-independent).

Follows docs/interfaces.md (contract v0.3, D2-D15, D28-D30). The ROS node
feeds it messages and the time; every method returns the messages to
publish as a list of (topic, data) pairs:

  /cmd_vel                            (linear, angular)
  /robot/state, /audio/play,
  /detect/request, /telegram/alert,
  /telegram/blocking                  str
  /avoidance/start, /avoidance/cancel,
  /password/start, /password/cancel   None (std_msgs/Empty)

``tick`` runs at a fixed rate. It handles the timeouts and always ends with
the /cmd_vel to send, so the wheels stop whenever an input goes quiet.
"""

from dataclasses import dataclass

DRIVE = "DRIVE"
CLASSIFY = "CLASSIFY"
ANNOUNCE = "ANNOUNCE"
AVOID = "AVOID"
CHECKPOINT = "CHECKPOINT"
PASS = "PASS"
WAIT_OPERATOR = "WAIT_OPERATOR"
BLOCKING = "BLOCKING"

# Gesture word -> (linear, angular) direction; anything else is zero speed
GESTURE_DIRECTIONS = {
    "forward": (1.0, 0.0),
    "back": (-1.0, 0.0),
    "left": (0.0, 1.0),
    "right": (0.0, -1.0),
}


@dataclass
class Settings:
    linear_speed: float = 0.2       # m/s for forward / back
    angular_speed: float = 1.0      # rad/s for left / right
    gesture_timeout: float = 0.5    # no /gesture/command this long -> stop (D4)
    obstacle_timeout: float = 1.0   # no /obstacle/detected this long -> blocked (D5)
    avoid_cmd_timeout: float = 0.5  # stale /avoidance/cmd_vel -> stop
    detect_timeout: float = 3.0     # per /detect/request, retried once (D7)
    announce_pause: float = 1.5     # ANNOUNCE -> AVOID
    pass_pause: float = 2.5         # PASS -> AVOID
    cleared_window: float = 20.0    # after PASS a person counts as unknown (D12)
    checkpoint_clear: float = 5.0   # path clear this long -> person left (D29)
    checkpoint_timeout: float = 60.0  # no /password/result (D30)
    operator_timeout: float = 30.0  # no Telegram decision (D15)
    blocking_repeat: float = 3.0    # alert + blocking clips
    back_hold: float = 1.0          # `back` held this long -> override (D11)
    avoid_timeout: float = 10.0     # no /avoidance/result (D30)


class StateMachine:
    def __init__(self, settings=None, now=0.0):
        self.s = settings or Settings()
        self.state = DRIVE
        self.entered_at = now
        self.gesture = "none"
        self.gesture_at = None
        self.back_since = None
        self.back_latched = False  # this hold already overrode once
        self.obstacle = True  # safe start: blocked until the sensor says clear
        self.obstacle_at = None
        self.clear_since = None
        self.avoid_cmd = (0.0, 0.0)
        self.avoid_cmd_at = None
        self.detect_id = None
        self.detect_sent_at = 0.0
        self.detect_retried = False
        self.alert_id = None
        self.passed_at = None
        self.announce_clip = None
        self.pass_clip = None
        self.blocking_next = 0.0
        self._counts = {}

    # Inputs

    def on_gesture(self, word, now):
        self.gesture = word
        self.gesture_at = now
        if word != "back":
            self.back_since = None
            self.back_latched = False
        elif self.back_since is None and not self.back_latched:
            self.back_since = now
        return []

    def on_obstacle(self, detected, now):
        appeared = detected and not self.obstacle
        self.obstacle = detected
        self.obstacle_at = now
        if detected:
            self.clear_since = None
        elif self.clear_since is None:
            self.clear_since = now
        # Edge trigger (D28): only an obstacle appearing starts CLASSIFY
        if appeared and self.state == DRIVE:
            return self._enter(CLASSIFY, now)
        return []

    def on_avoidance_cmd(self, linear, angular, now):
        self.avoid_cmd = (linear, angular)
        self.avoid_cmd_at = now
        return []

    def on_avoidance_result(self, result, now):
        if self.state != AVOID:
            return []
        if result == "done":
            return self._enter(DRIVE, now)
        return self._avoid_failed(now)

    def on_detect_result(self, reply, now):
        if self.state != CLASSIFY or reply.get("id") != self.detect_id:
            return []
        kind = reply.get("kind")
        cleared = (self.passed_at is not None
                   and now - self.passed_at < self.s.cleared_window)
        if kind == "person" and cleared:
            self.announce_clip = "found_obstacle"
        elif kind in ("object", "unknown"):
            self.announce_clip = reply.get("clip") or "found_obstacle"
        else:
            # A person, or a reply we don't understand: never skip the password
            return self._enter(CHECKPOINT, now)
        return self._enter(ANNOUNCE, now)

    def on_password_result(self, result, now):
        if self.state != CHECKPOINT:
            return []
        if result == "granted":
            self.pass_clip = "password_correct"
            return self._enter(PASS, now)
        return self._enter(WAIT_OPERATOR, now)

    def on_telegram_decision(self, reply, now):
        if reply.get("id") != self.alert_id:
            return []
        decision = reply.get("decision")
        if self.state == WAIT_OPERATOR and decision == "allow":
            self.pass_clip = "operator_allowed"
            return self._enter(PASS, now)
        if self.state == WAIT_OPERATOR and decision == "deny":
            return self._enter(BLOCKING, now)
        if self.state == BLOCKING and decision == "resume":
            return self._enter(AVOID, now)
        return []

    def tick(self, now):
        if not self._gesture_fresh(now):
            self.back_since = None
            self.back_latched = False
        if self._obstacle_silent(now):
            self.clear_since = None
        out = self._timeouts(now)
        out.append(("/cmd_vel", self._wheels(now)))
        return out

    # Internals

    def _timeouts(self, now):
        s = self.s
        in_state = now - self.entered_at
        if (self.state != DRIVE and self.back_since is not None
                and now - max(self.back_since, self.entered_at) >= s.back_hold):
            self.back_since = None
            self.back_latched = True  # release `back` before it counts again
            if self.state == BLOCKING:
                return self._enter(AVOID, now)
            return self._cancel_running() + self._enter(DRIVE, now)

        if self.state == CLASSIFY and now - self.detect_sent_at >= s.detect_timeout:
            if not self.detect_retried:
                self.detect_retried = True
                return self._request_detect(now)
            return self._enter(CHECKPOINT, now)
        if self.state == ANNOUNCE and in_state >= s.announce_pause:
            return self._enter(AVOID, now)
        if self.state == PASS and in_state >= s.pass_pause:
            self.passed_at = now
            return self._enter(AVOID, now)
        if self.state == CHECKPOINT:
            if self.clear_since is not None and now - self.clear_since >= s.checkpoint_clear:
                return [("/password/cancel", None)] + self._enter(DRIVE, now)
            if in_state >= s.checkpoint_timeout:
                return [("/password/cancel", None)] + self._enter(WAIT_OPERATOR, now)
        if self.state == WAIT_OPERATOR and in_state >= s.operator_timeout:
            return self._enter(BLOCKING, now)
        if self.state == BLOCKING and now >= self.blocking_next:
            return self._blocking_clips(now)
        if self.state == AVOID and in_state >= s.avoid_timeout:
            return [("/avoidance/cancel", None)] + self._avoid_failed(now)
        return []

    def _enter(self, state, now):
        self.state = state
        self.entered_at = now
        out = [("/robot/state", state)]
        if state == CLASSIFY:
            self.detect_retried = False
            out += self._request_detect(now)
        elif state == ANNOUNCE:
            out.append(("/audio/play", self.announce_clip))
        elif state == AVOID:
            self.avoid_cmd_at = None  # don't replay a turn from the last run
            out.append(("/avoidance/start", None))
        elif state == CHECKPOINT:
            out.append(("/password/start", None))
        elif state == PASS:
            out.append(("/audio/play", self.pass_clip))
        elif state == WAIT_OPERATOR:
            self.alert_id = self._new_id("a")
            out.append(("/telegram/alert", self.alert_id))
        elif state == BLOCKING:
            self.alert_id = self._new_id("a")
            out.append(("/telegram/blocking", self.alert_id))
            out += self._blocking_clips(now)
        return out

    def _request_detect(self, now):
        self.detect_id = self._new_id("d")
        self.detect_sent_at = now
        return [("/detect/request", self.detect_id)]

    def _blocking_clips(self, now):
        # `alert` interrupts, so it goes first (interfaces.md, Audio)
        self.blocking_next = now + self.s.blocking_repeat
        return [("/audio/play", "alert"), ("/audio/play", "blocking")]

    def _avoid_failed(self, now):
        # D6: stop, say so, hand driving back to the operator
        return self._enter(DRIVE, now) + [("/audio/play", "found_obstacle")]

    def _cancel_running(self):
        if self.state == CHECKPOINT:
            return [("/password/cancel", None)]
        if self.state == AVOID:
            return [("/avoidance/cancel", None)]
        return []

    def _new_id(self, prefix):
        self._counts[prefix] = self._counts.get(prefix, 0) + 1
        return "%s%d" % (prefix, self._counts[prefix])

    def _gesture_fresh(self, now):
        return self.gesture_at is not None and now - self.gesture_at < self.s.gesture_timeout

    def _obstacle_silent(self, now):
        return self.obstacle_at is None or now - self.obstacle_at > self.s.obstacle_timeout

    def _wheels(self, now):
        if not self._gesture_fresh(now) or self.gesture == "stop":
            return (0.0, 0.0)
        if self.state == DRIVE:
            if self.gesture == "forward" and (self.obstacle or self._obstacle_silent(now)):
                return (0.0, 0.0)
            lin, ang = GESTURE_DIRECTIONS.get(self.gesture, (0.0, 0.0))
            return (lin * self.s.linear_speed, ang * self.s.angular_speed)
        if (self.state == AVOID and self.avoid_cmd_at is not None
                and now - self.avoid_cmd_at < self.s.avoid_cmd_timeout):
            return self.avoid_cmd
        return (0.0, 0.0)
