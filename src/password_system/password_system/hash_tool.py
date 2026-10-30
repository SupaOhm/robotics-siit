"""Generate the password_hash / salt pair for config/password.yaml.

    ros2 run password_system make_password_hash one three five two
    python -m password_system.hash_tool "open sesame"

The password is normalized first (see normalize.py), so "one three five
two", "1 3 5 2" and "1352" all give the same hash.
"""

import argparse

from .normalize import normalize
from .verifier import hash_password, make_salt


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("password", nargs="+", help="the spoken password")
    args = parser.parse_args(argv)

    normalized = normalize(" ".join(args.password))
    if not normalized:
        parser.error("password is empty after normalization")

    salt = make_salt()
    print("# normalized: %s" % normalized)
    print("    password_chars: %d" % len(normalized))
    print('    salt: "%s"' % salt)
    print('    password_hash: "%s"' % hash_password(normalized, salt))


if __name__ == "__main__":
    main()
