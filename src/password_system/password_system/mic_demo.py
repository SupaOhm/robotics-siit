"""Try the spoken password on a laptop microphone, no ROS needed.

    pip install SpeechRecognition pyaudio vosk
    python -m password_system.mic_demo --password 4719      # any test digits

Press Enter to start a session, Ctrl+C to quit.
"""

import argparse

from .normalize import normalize
from .speech import ENGINES, SpeechListener
from .verifier import EventType, PasswordVerifier, hash_password, make_salt


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--password", required=True, help="a test password, e.g. 4719")
    parser.add_argument("--engine", choices=ENGINES, default="vosk")
    parser.add_argument("--language", default="en-US")
    parser.add_argument("--device", type=int, default=None, help="microphone index")
    parser.add_argument("--vosk-model", default="")
    parser.add_argument("--attempts", type=int, default=3)
    parser.add_argument("--match", choices=("contains", "exact"), default="contains")
    args = parser.parse_args(argv)

    normalized = normalize(args.password)
    salt = make_salt()
    verifier = PasswordVerifier(hash_password(normalized, salt), salt, len(normalized),
                                args.attempts, args.match)
    print("Calibrating for background noise, stay quiet...")
    listener = SpeechListener(engine=args.engine, language=args.language,
                              device_index=args.device, vosk_model_path=args.vosk_model)

    try:
        while True:
            input("\nPress Enter to start a session ")
            events = verifier.start()
            while verifier.active:
                print("  listening... say the password")
                result = listener.listen_once()
                if result.kind == "no_speech":
                    events = verifier.no_speech()
                elif result.kind == "error":
                    print("  error: %s" % result.error)
                    events = verifier.service_error()
                else:
                    print("  heard: %s" % result.candidates)
                    events = verifier.submit(result.candidates)
                for ev in events:
                    print("  -> %s (attempts left %d)" % (ev.type.value, ev.attempts_left))
                    if ev.type == EventType.LOCKED_OUT:
                        print("  DENIED: alert + Telegram would start here")
    except (KeyboardInterrupt, EOFError):
        print()


if __name__ == "__main__":
    main()
