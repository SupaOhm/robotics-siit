import pytest

from robot_core.machine import (ANNOUNCE, AVOID, BLOCKING, CHECKPOINT, CLASSIFY,
                                DRIVE, PASS, WAIT_OPERATOR, StateMachine)


class Robot:
    """Drives a StateMachine with a fake clock: gestures and the obstacle
    sensor keep arriving at 10 Hz, like the real nodes."""

    def __init__(self):
        self.t = 0.0
        self.m = StateMachine(now=0.0)
        self.gesture = "none"
        self.obstacle = False
        self.out = []
        self.wait(0.2)

    def wait(self, seconds, gesture=True, obstacle=True):
        end = self.t + seconds
        while self.t < end - 1e-9:
            self.t = round(self.t + 0.1, 6)
            if gesture:
                self.out += self.m.on_gesture(self.gesture, self.t)
            if obstacle:
                self.out += self.m.on_obstacle(self.obstacle, self.t)
            self.out += self.m.tick(self.t)

    def send(self, handler, *args):
        self.out += getattr(self.m, handler)(*args, self.t)

    def sent(self, topic):
        return [d for t, d in self.out if t == topic]

    def wheels(self):
        return self.sent("/cmd_vel")[-1]

    def to_classify(self):
        self.obstacle = True
        self.wait(0.1)
        assert self.m.state == CLASSIFY
        return self.sent("/detect/request")[-1]

    def to_checkpoint(self):
        rid = self.to_classify()
        self.send("on_detect_result", {"id": rid, "kind": "person"})
        assert self.m.state == CHECKPOINT

    def to_wait_operator(self):
        self.to_checkpoint()
        self.send("on_password_result", "denied")
        assert self.m.state == WAIT_OPERATOR
        return self.sent("/telegram/alert")[-1]

    def to_blocking(self):
        aid = self.to_wait_operator()
        self.send("on_telegram_decision", {"id": aid, "decision": "deny"})
        assert self.m.state == BLOCKING
        return self.sent("/telegram/blocking")[-1]


@pytest.fixture
def r():
    return Robot()


# Driving

@pytest.mark.parametrize("word, wheels", [
    ("forward", (0.2, 0.0)), ("back", (-0.2, 0.0)), ("left", (0.0, 1.0)),
    ("right", (0.0, -1.0)), ("stop", (0.0, 0.0)), ("none", (0.0, 0.0)),
])
def test_gestures_drive(r, word, wheels):
    r.gesture = word
    r.wait(0.1)
    assert r.wheels() == wheels


def test_no_gesture_for_half_a_second_stops(r):
    r.gesture = "forward"
    r.wait(0.5)
    r.wait(0.6, gesture=False)
    assert r.wheels() == (0.0, 0.0)


def test_forward_blocked_by_obstacle_but_turning_allowed(r):
    r.to_classify()
    r.m.state = DRIVE  # as after avoidance failed
    r.gesture = "forward"
    r.wait(0.1)
    assert r.wheels() == (0.0, 0.0)
    r.gesture = "left"
    r.wait(0.1)
    assert r.wheels() == (0.0, 1.0)


def test_obstacle_silence_blocks_forward_but_never_classifies(r):
    r.gesture = "forward"
    r.wait(1.5, obstacle=False)
    assert r.wheels() == (0.0, 0.0)
    assert r.m.state == DRIVE


def test_blocked_from_start_until_the_sensor_reports():
    m = StateMachine(now=0.0)
    m.on_gesture("forward", 0.1)
    assert m.tick(0.1)[-1] == ("/cmd_vel", (0.0, 0.0))
    # The sensor's start-up `true` is not an obstacle appearing
    assert m.on_obstacle(True, 0.1) == []


# Obstacle -> detection

def test_obstacle_appearing_requests_detection_and_stops(r):
    r.gesture = "left"
    rid = r.to_classify()
    assert rid == "d1"
    assert r.wheels() == (0.0, 0.0)


def test_classify_stops_the_wheels_before_the_request(r):
    # The detector's frame must not be taken while the robot still moves
    r.gesture = "left"
    r.wait(0.1)
    r.out.clear()
    r.send("on_obstacle", True)
    topics = [t for t, _ in r.out]
    assert r.out[topics.index("/cmd_vel")] == ("/cmd_vel", (0.0, 0.0))
    assert topics.index("/cmd_vel") < topics.index("/detect/request")


def test_object_announced_then_avoided_then_drive(r):
    rid = r.to_classify()
    r.send("on_detect_result", {"id": rid, "kind": "object", "label": "chair",
                                "confidence": 0.8, "clip": "found_chair"})
    assert r.m.state == ANNOUNCE
    assert r.sent("/audio/play") == ["found_chair"]
    r.wait(1.9)  # found_* clips run up to 1.99 s
    assert r.m.state == ANNOUNCE
    r.wait(0.2)
    assert r.m.state == AVOID
    assert r.sent("/avoidance/start") == [None]
    r.send("on_avoidance_result", "done")
    assert r.m.state == DRIVE


def test_unknown_says_found_obstacle(r):
    rid = r.to_classify()
    r.send("on_detect_result", {"id": rid, "kind": "unknown", "clip": None})
    assert r.sent("/audio/play") == ["found_obstacle"]


def test_reply_with_old_id_ignored(r):
    r.to_classify()
    r.send("on_detect_result", {"id": "d99", "kind": "object", "clip": "found_chair"})
    assert r.m.state == CLASSIFY


def test_no_detector_reply_retries_once_then_checkpoint(r):
    r.to_classify()
    r.wait(3.0)
    assert r.sent("/detect/request") == ["d1", "d2"]
    assert r.m.state == CLASSIFY
    r.send("on_detect_result", {"id": "d1", "kind": "object", "clip": "found_chair"})
    assert r.m.state == CLASSIFY  # first id is stale after the retry
    r.wait(3.0)
    assert r.m.state == CHECKPOINT


def test_strange_detector_reply_goes_to_checkpoint(r):
    rid = r.to_classify()
    r.send("on_detect_result", {"id": rid, "kind": "cat"})
    assert r.m.state == CHECKPOINT


# Avoidance

def test_avoidance_cmd_forwarded_only_in_avoid(r):
    r.send("on_avoidance_cmd", 0.0, 0.5)
    r.wait(0.1)
    assert r.wheels() == (0.0, 0.0)
    rid = r.to_classify()
    r.send("on_detect_result", {"id": rid, "kind": "unknown"})
    r.wait(2.1)
    assert r.m.state == AVOID
    r.send("on_avoidance_cmd", 0.0, 0.5)
    r.wait(0.1)
    assert r.wheels() == (0.0, 0.5)
    r.gesture = "stop"
    r.wait(0.1)
    assert r.wheels() == (0.0, 0.0)


def test_avoidance_failed_says_obstacle_and_drives(r):
    rid = r.to_classify()
    r.send("on_detect_result", {"id": rid, "kind": "unknown"})
    r.wait(2.1)
    r.out.clear()
    r.send("on_avoidance_result", "failed")
    assert r.m.state == DRIVE
    assert r.sent("/audio/play") == ["found_obstacle"]
    r.wait(1.0)  # obstacle still there: no new CLASSIFY (D28)
    assert r.m.state == DRIVE


def test_avoidance_timeout_cancels_and_fails(r):
    rid = r.to_classify()
    r.send("on_detect_result", {"id": rid, "kind": "unknown"})
    r.wait(2.1)
    r.out.clear()
    r.wait(10.0)
    assert r.sent("/avoidance/cancel") == [None]
    assert r.sent("/audio/play") == ["found_obstacle"]
    assert r.m.state == DRIVE


# Checkpoint

def test_person_starts_password(r):
    r.to_checkpoint()
    assert r.sent("/password/start") == [None]
    assert r.wheels() == (0.0, 0.0)


def test_granted_passes_then_avoids(r):
    r.to_checkpoint()
    r.send("on_password_result", "granted")
    assert r.m.state == PASS
    assert r.sent("/audio/play") == ["password_correct"]
    r.wait(2.5)
    assert r.m.state == AVOID


def test_cleared_person_within_20_s_is_an_obstacle(r):
    r.to_checkpoint()
    r.send("on_password_result", "granted")
    r.wait(2.5)
    r.send("on_avoidance_result", "done")
    r.obstacle = False
    r.wait(1.0)
    r.out.clear()
    rid = r.to_classify()
    r.send("on_detect_result", {"id": rid, "kind": "person"})
    assert r.m.state == ANNOUNCE
    assert r.sent("/audio/play") == ["found_obstacle"]


def test_person_after_20_s_asked_again(r):
    r.to_checkpoint()
    r.send("on_password_result", "granted")
    r.wait(2.5)
    r.send("on_avoidance_result", "done")
    r.obstacle = False
    r.wait(20.0)
    r.to_checkpoint()


def test_person_walks_away_cancels_password(r):
    r.to_checkpoint()
    r.obstacle = False
    r.wait(4.9)
    assert r.m.state == CHECKPOINT
    r.wait(0.2)
    assert r.m.state == DRIVE
    assert r.sent("/password/cancel") == [None]


def test_cancelled_from_an_old_session_is_ignored(r):
    # We only cancel on leaving CHECKPOINT, so this belongs to an old session
    r.to_checkpoint()
    r.send("on_password_result", "cancelled")
    assert r.m.state == CHECKPOINT
    assert r.sent("/telegram/alert") == []


def test_password_stuck_goes_to_operator(r):
    r.to_checkpoint()
    r.wait(60.0)
    assert r.sent("/password/cancel") == [None]
    assert r.m.state == WAIT_OPERATOR


# Operator

def test_denied_alerts_operator_who_allows(r):
    aid = r.to_wait_operator()
    assert aid == "a1"
    r.send("on_telegram_decision", {"id": aid, "decision": "allow"})
    assert r.m.state == PASS
    assert r.sent("/audio/play")[-1] == "operator_allowed"


def test_decision_for_old_alert_ignored(r):
    r.to_wait_operator()
    r.send("on_telegram_decision", {"id": "a0", "decision": "allow"})
    r.send("on_telegram_decision", {"id": "a1", "decision": "resume"})
    assert r.m.state == WAIT_OPERATOR


def test_operator_timeout_blocks_with_new_id(r):
    r.to_wait_operator()
    r.wait(30.0)
    assert r.m.state == BLOCKING
    assert r.sent("/telegram/blocking") == ["a2"]


def test_blocking_repeats_alert_then_blocking_every_3_s(r):
    r.to_blocking()
    r.out.clear()
    r.wait(6.0)
    assert r.sent("/audio/play") == ["alert", "blocking", "alert", "blocking"]
    assert r.wheels() == (0.0, 0.0)


def test_resume_turns_away(r):
    bid = r.to_blocking()
    r.send("on_telegram_decision", {"id": "a1", "decision": "resume"})
    assert r.m.state == BLOCKING  # old alert's id
    r.send("on_telegram_decision", {"id": bid, "decision": "resume"})
    assert r.m.state == AVOID


# Back held 1 s (D11)

def test_back_held_ends_blocking_into_avoid_once(r):
    r.to_blocking()
    r.gesture = "back"
    r.wait(0.9)
    assert r.m.state == BLOCKING
    r.wait(0.3)
    assert r.m.state == AVOID
    r.wait(2.0)  # still holding: doesn't also cancel the turn
    assert r.m.state == AVOID


def test_back_held_overrides_checkpoint(r):
    r.to_checkpoint()
    r.gesture = "back"
    r.wait(1.2)
    assert r.m.state == DRIVE
    assert r.sent("/password/cancel") == [None]


def test_back_held_overrides_avoid(r):
    rid = r.to_classify()
    r.send("on_detect_result", {"id": rid, "kind": "unknown"})
    r.wait(2.1)
    r.gesture = "back"
    r.wait(1.2)
    assert r.m.state == DRIVE
    assert r.sent("/avoidance/cancel") == [None]


def test_reversing_into_a_person_never_skips_the_password(r):
    # Reversing in DRIVE isn't an override: the operator must release `back`
    r.gesture = "back"
    r.wait(2.0)
    r.to_checkpoint()
    r.wait(3.0)
    assert r.m.state == CHECKPOINT
    assert r.sent("/password/cancel") == []
    r.gesture = "none"
    r.wait(0.1)
    r.gesture = "back"
    r.wait(1.2)
    assert r.m.state == DRIVE
    assert r.sent("/password/cancel") == [None]


def test_back_broken_by_another_gesture_restarts_the_hold(r):
    r.to_checkpoint()
    r.gesture = "back"
    r.wait(0.6)
    r.gesture = "none"
    r.wait(0.1)
    r.gesture = "back"
    r.wait(0.6)
    assert r.m.state == CHECKPOINT
