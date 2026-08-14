"""Crash-safe persistence of the monitor's cross-poll state (acknowledgements,
message->fixture map, pending stake/price prompts, bets, telegram offset).

Kept deliberately dumb: a plain JSON blob. If it fails to load, the monitor
starts clean rather than dying.
"""
import json
import os


def save(path, data):
    try:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh)
    except Exception as e:
        print("  ! state save failed:", e, flush=True)


def load(path):
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception as e:
        print("  ! state load failed:", e, flush=True)
        return None
