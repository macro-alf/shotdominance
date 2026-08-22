#!/usr/bin/env python3
"""Send logs/reminder.txt to Telegram, then clear it.

    python remind.py            # send and clear
    python remind.py --print    # show what would be sent

Deliberately trivial. Claude session crons die with the session and mobile push
is disabled, so the only channel that reliably reaches Alf is the Telegram bot
the monitor already uses. Pairing this with a one-shot Windows task gives a
reminder that survives the PC sleeping.
"""
import os
import sys

PATH = os.path.join("logs", "reminder.txt")


def main():
    try:
        with open(PATH, encoding="utf-8") as fh:
            text = fh.read().strip()
    except FileNotFoundError:
        print("no reminder pending")
        return 0
    if not text:
        print("reminder file is empty")
        return 0

    print(text)
    if "--print" in sys.argv:
        return 0

    from shotdominance import telegram
    tg = telegram.Telegram()
    if not tg.enabled:
        print("[telegram not configured - not sent, reminder kept]")
        return 1
    tg.send(text)
    os.remove(PATH)          # fire once, do not nag
    return 0


if __name__ == "__main__":
    sys.exit(main())
