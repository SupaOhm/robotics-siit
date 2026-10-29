"""Generate the password_hash / salt pair for config/password.yaml.

    ros2 run password_system make_password_hash 1352
    python -m password_system.hash_tool 1352
"""

import argparse

from .gesture_input import DEFAULT_TOKENS
from .verifier import hash_password, make_salt


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("password", help="digits 1-5, e.g. 1352")
    args = parser.parse_args(argv)

    bad = [c for c in args.password if c not in DEFAULT_TOKENS]
    if bad or not args.password:
        parser.error("password must only contain digits 1-5 (fingers raised)")

    salt = make_salt()
    print("    password_length: %d" % len(args.password))
    print('    salt: "%s"' % salt)
    print('    password_hash: "%s"' % hash_password(args.password, salt))


if __name__ == "__main__":
    main()
