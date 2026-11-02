"""Try the spoken password on a laptop microphone, no ROS needed.

    pip install SpeechRecognition pyaudio vosk
    python -m password_system.mic_demo --password 4719 --vosk-model ~/vosk-model-small-en-us-0.15

Press Enter to start a session, Ctrl+C to quit.
"""

import argparse

from .normalize import normalize
from .speech import ENGINES, SpeechListener
from .verifier import MATCH_MODES, EventType, PasswordVerifier, hash_password, make_salt


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--password", required=True, help="a test password, e.g. 4719")
    parser.add_argument("--engine", choices=ENGINES, default="vosk")
    parser.add_argument("--language", default="en-US")
    parser.add_argument("--device", type=int, default=None, help="microphone index")
    parser.add_argument("--vosk-model", default="", help="unzipped Vosk model folder")
    parser.add_argument("--attempts", type=int, default=3)
    parser.add_argument("--match", choices=MATCH_MODES, default="exact")
    args = parser.parse_args(argv)

    normalized = normalize(args.password)
    salt = make_salt()
    verifier = PasswordVerifier(hash_password(normalized, salt), salt, len(normalized),
                                args.attempts, args.match)
    listener = SpeechListener(engine=args.engine, language=args.language,
                              device_index=args.device, vosk_model_path=args.vosk_model)
    print("Calibrating for background noise, stay quiet...")
    listener.calibrate()

    try:
        while True:
            input("\nPress Enter to start a session ")
            verifier.start()
            while verifier.active:
                print("  listening... say the password")
                result = listener.listen_once()
                if result.kind == "error":
                    print("  error: %s" % result.error)
                elif result.kind == "speech":
                    print("  heard: %s" % result.candidates)
                for ev in verifier.handle(result):
                    print("  -> %s (attempts left %d)" % (ev.type.value, ev.attempts_left))
                    if ev.type == EventType.LOCKED_OUT:
                        print("  DENIED: alert + Telegram would start here")
    except (KeyboardInterrupt, EOFError):
        print()


if __name__ == "__main__":
    main()
