"""Generate the password settings for the robot (kept out of the repo).

    ros2 run password_system make_password_hash 4 7 1 9
    python -m password_system.hash_tool four seven one nine

Prints ROBOT_PASSWORD_* lines. Put them in the robot's ~/.bashrc (with
"export") or in the gitignored .env file, never in config/password.yaml.

The password is normalized first (see normalize.py), so "four seven one
nine", "4 7 1 9" and "4719" all give the same hash. It must be digits
(contract D23), because the Vosk engine only knows the digit words.
"""

import argparse

from .normalize import normalize
from .verifier import hash_password, make_salt


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("password", nargs="+", help="the spoken digits")
    parser.add_argument("--allow-words", action="store_true",
                        help="allow non-digit words (google engine only)")
    args = parser.parse_args(argv)

    normalized = normalize(" ".join(args.password))
    if not normalized:
        parser.error("password is empty after normalization")
    if not normalized.isdigit() and not args.allow_words:
        parser.error("password must be digits (Vosk only knows digit words); "
                     "use --allow-words for the google engine")

    salt = make_salt()
    print("export ROBOT_PASSWORD_SALT=%s" % salt)
    print("export ROBOT_PASSWORD_HASH=%s" % hash_password(normalized, salt))
    print("export ROBOT_PASSWORD_CHARS=%d" % len(normalized))


if __name__ == "__main__":
    main()
