"""Try the Telegram flow from a laptop, no ROS needed.

    pip install python-telegram-bot
    python -m telegram_alert.bot_demo --env-file ../../.env --image person.jpg

Plays the state machine's part: sends an alert, waits up to --timeout seconds
for Allow / Deny, then (after Deny or no answer) sends "Robot is blocking"
and waits for Resume. Decisions are printed as they would be published.
"""

import argparse
import asyncio
import json

from .bot import AlertBot
from .settings import load_settings


async def wait_for(decisions: asyncio.Queue, timeout: float):
    try:
        return await asyncio.wait_for(decisions.get(), timeout)
    except asyncio.TimeoutError:
        return None


async def run(args) -> None:
    settings = load_settings(env_file=args.env_file)
    jpeg = None
    if args.image:
        with open(args.image, "rb") as f:
            jpeg = f.read()

    decisions: asyncio.Queue = asyncio.Queue()

    def on_decision(decision):
        print("/telegram/decision:", json.dumps(decision))
        decisions.put_nowait(decision)

    bot = AlertBot(settings, on_decision)
    await bot.start()
    try:
        print("Sending alert demo1, answer in Telegram within %.0f s..." % args.timeout)
        await bot.alert("demo1", jpeg, "" if jpeg else "(demo: no image)")
        decision = await wait_for(decisions, args.timeout)
        if decision and decision["decision"] == "allow":
            print("Allowed: the robot would announce the person may pass.")
            return
        print("Denied or no answer: the robot blocks. Sending blocking demo2...")
        await bot.blocking("demo2")
        decision = await wait_for(decisions, args.resume_wait)
        print("Resumed." if decision else "No Resume pressed, demo over.")
    finally:
        await bot.stop()


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", default="", help=".env with TELEGRAM_* values")
    parser.add_argument("--image", default="", help="JPEG to send as the person's photo")
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--resume-wait", type=float, default=120.0)
    try:
        asyncio.run(run(parser.parse_args(argv)))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
