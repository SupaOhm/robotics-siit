"""Generate the password settings for the robot (kept out of the repo).

    ros2 run password_system make_password_hash 4 7 1 9
    python -m password_system.hash_tool four seven one nine

Prints one ROBOT_PASSWORD_HASH line (length, salt and hash together). Put
it in the robot's ~/.bashrc or in the gitignored .env file, never in
config/password.yaml.

The password is normalized first (see normalize.py), so "four seven one
nine", "4 7 1 9" and "4719" all give the same hash. It must be digits
(contract D23), because the Vosk engine only knows the digit words.
"""

import argparse

from .normalize import normalize
from .verifier import make_stored


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("password", nargs="+", help="the spoken digits")
    args = parser.parse_args(argv)

    normalized = normalize(" ".join(args.password))
    if not normalized.isdigit():
        parser.error("password must be digits (contract D23; Vosk only knows "
                     "digit words)")

    print("export ROBOT_PASSWORD_HASH=%s" % make_stored(normalized))


if __name__ == "__main__":
    main()
