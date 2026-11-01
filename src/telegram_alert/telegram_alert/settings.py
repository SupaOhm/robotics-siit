"""Bot token and chat id from the environment (never from the repo).

    TELEGRAM_BOT_TOKEN      from @BotFather
    TELEGRAM_CHAT_ID        the operator chat (send /start to the bot to see it)
    TELEGRAM_ALLOWED_USERS  optional, comma-separated Telegram user ids that
                            may press the buttons (empty = anyone in the chat)

They can also live in a gitignored .env file (KEY=VALUE lines) passed as
``env_file``. Variables already set in the environment win over the file.
"""

import os
from dataclasses import dataclass, field
from typing import Dict, FrozenSet, Mapping, Optional


@dataclass(frozen=True)
class Settings:
    token: str = field(repr=False)  # keep it out of logs and tracebacks
    chat_id: int
    allowed_users: FrozenSet[int]


def parse_env_file(text: str) -> Dict[str, str]:
    """KEY=VALUE lines; '#' comments (also after an unquoted value), blank
    lines, 'export ' and quotes allowed."""
    values = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export "):]
        key, _, value = line.partition("=")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        else:
            value = value.split(" #", 1)[0].strip()
        values[key.strip()] = value
    return values


def parse_user_ids(text: str) -> FrozenSet[int]:
    return frozenset(int(part) for part in text.replace(" ", "").split(",") if part)


def load_settings(environ: Optional[Mapping[str, str]] = None,
                  env_file: str = "") -> Settings:
    env = dict(os.environ if environ is None else environ)
    if env_file:
        with open(os.path.expanduser(env_file), encoding="utf-8") as f:
            for key, value in parse_env_file(f.read()).items():
                env.setdefault(key, value)

    token = env.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = env.get("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID must be set "
            "(environment or env_file). See src/telegram_alert/README.md.")
    try:
        chat = int(chat_id)
        users = parse_user_ids(env.get("TELEGRAM_ALLOWED_USERS", ""))
    except ValueError as e:
        raise RuntimeError("TELEGRAM_CHAT_ID / TELEGRAM_ALLOWED_USERS must be numbers: %s" % e)
    return Settings(token, chat, users)
