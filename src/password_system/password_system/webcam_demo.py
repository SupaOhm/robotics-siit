"""Try the password flow on a laptop webcam, no ROS needed.

    pip install opencv-python mediapipe
    python -m password_system.webcam_demo --password 1352

Press s to start a session, q to quit.
"""

import argparse
import time

import cv2

from .finger_counter import HandFingerCounter
from .gesture_input import GestureDebouncer
from .verifier import EventType, PasswordVerifier, hash_password, make_salt


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--password", default="1352")
    parser.add_argument("--camera", type=int, default=0)
    parser.add_argument("--attempts", type=int, default=3)
    parser.add_argument("--timeout", type=float, default=15.0)
    args = parser.parse_args(argv)

    salt = make_salt()
    verifier = PasswordVerifier(hash_password(args.password, salt), salt,
                                len(args.password), args.attempts, args.timeout)
    debouncer = GestureDebouncer()
    counter = HandFingerCounter()
    cap = cv2.VideoCapture(args.camera)
    status = "press s to start"

    def show(events):
        nonlocal status
        for ev in events:
            print(ev.to_dict())
            status = "%s | attempts left %d" % (ev.type.value, ev.attempts_left)
            if ev.type == EventType.LOCKED_OUT:
                status = "DENIED -> alert / Telegram"
            elif ev.type == EventType.GRANTED:
                status = "GRANTED"

    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            frame = cv2.flip(frame, 1)
            now = time.monotonic()
            fingers = counter.count(frame)
            if verifier.active:
                token = debouncer.update(fingers, now)
                if token is not None:
                    show(verifier.feed(token, now))
                show(verifier.tick(now))

            cand, frac = debouncer.progress(now)
            entered = "*" * verifier.tokens_entered + "_" * (
                verifier.password_length - verifier.tokens_entered)
            cv2.putText(frame, "fingers: %s" % ("-" if fingers is None else fingers),
                        (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)
            cv2.putText(frame, "code: %s" % entered, (10, 65),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 255), 2)
            cv2.putText(frame, status, (10, 100), cv2.FONT_HERSHEY_SIMPLEX,
                        0.7, (255, 255, 255), 2)
            if verifier.active and cand is not None:
                cv2.rectangle(frame, (10, 115), (10 + int(200 * frac), 130),
                              (0, 200, 255), -1)
            cv2.imshow("password demo", frame)

            key = cv2.waitKey(1) & 0xFF
            if key == ord("q"):
                break
            if key == ord("s"):
                debouncer.reset()
                show(verifier.start(now))
    finally:
        counter.close()
        cap.release()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
