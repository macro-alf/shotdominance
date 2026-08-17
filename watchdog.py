#!/usr/bin/env python3
"""Watch the supervisor from outside it, and say so on Telegram when it dies.

    python watchdog.py            # check once, alert + self-heal if needed
    python watchdog.py --status   # print what it sees, change nothing

WHY THIS EXISTS
  Every alert in this system lived inside monitor.py - the blind-feed warning,
  the quota warning, the bet alerts. All of them are useless when the SUPERVISOR
  is the thing that died, because then monitor.py is never launched at all. On
  2026-08-17 daily.py stopped at 13:49 with no traceback, no log line and no
  Telegram; the evening's six fixtures would simply have gone unwatched, and it
  was caught only because somebody happened to look.

  So this runs as its own scheduled task. It reads the heartbeat daily.py
  publishes, and if that heartbeat has gone stale while the day is still live it
  sends Telegram and restarts the scheduled task.

DELIBERATE EXITS ARE NOT FAILURES
  daily.py stamps a state as well as a time. 'finished' and 'aborted' mean it
  meant to stop (day over, or too little quota to run safely), so a stale
  heartbeat in those states is left alone - otherwise this would restart the day
  every night after the PC goes to sleep.

SEND-ONLY, BY DESIGN
  Telegram getUpdates is a single-consumer cursor, so a second reader would
  steal the monitor's replies. This only ever calls sendMessage, which is safe
  to do from any number of processes.
"""
import datetime as dt
import os
import subprocess
import sys

from shotdominance import telegram

HEARTBEAT = os.path.join("logs", "heartbeat.txt")
LAST_ACTION = os.path.join("logs", "watchdog-last.txt")
TASK = os.getenv("MONITOR_TASK", "InplayMonitor")

# daily.py beats at least every 10 minutes while waiting and every 5 while
# supervising, so 25 minutes of silence is unambiguous rather than a slow poll.
STALE_MIN = int(os.getenv("WATCHDOG_STALE_MIN", "25"))
# Only act inside the window where the supervisor is expected to be up. Outside
# it the PC is usually asleep and this task is not running anyway.
ACTIVE_FROM, ACTIVE_TO = 8, 1          # 08:00 -> 01:00 next day
RESTART_COOLDOWN_MIN = int(os.getenv("WATCHDOG_COOLDOWN_MIN", "60"))
OK_STATES = ("finished", "aborted")


def read_heartbeat():
    """-> (age_minutes, state) or (None, None) when there is no heartbeat."""
    try:
        with open(HEARTBEAT, encoding="utf-8") as fh:
            stamp, _, state = fh.read().strip().partition(" ")
        age = (dt.datetime.now() - dt.datetime.fromisoformat(stamp))
        return age.total_seconds() / 60.0, (state or "unknown").strip()
    except Exception:
        return None, None


def in_active_window(now=None):
    h = (now or dt.datetime.now()).hour
    return h >= ACTIVE_FROM or h < ACTIVE_TO


def recently_acted():
    try:
        with open(LAST_ACTION, encoding="utf-8") as fh:
            when = dt.datetime.fromisoformat(fh.read().strip())
    except Exception:
        return False
    return (dt.datetime.now() - when).total_seconds() / 60.0 < RESTART_COOLDOWN_MIN


def mark_acted():
    try:
        os.makedirs("logs", exist_ok=True)
        with open(LAST_ACTION, "w", encoding="utf-8") as fh:
            fh.write(dt.datetime.now().isoformat(timespec="seconds"))
    except Exception:
        pass


def diagnose():
    """-> (problem_or_None, detail). Pure: makes no changes, sends nothing."""
    age, state = read_heartbeat()
    if not in_active_window():
        return None, "outside the active window"
    if age is None:
        return "no heartbeat", "logs/heartbeat.txt missing or unreadable"
    if state in OK_STATES:
        return None, "state=%s (deliberate), %.0f min old" % (state, age)
    if age > STALE_MIN:
        return ("stale heartbeat",
                "state=%s, last beat %.0f min ago (limit %d)"
                % (state, age, STALE_MIN))
    return None, "state=%s, %.0f min old" % (state, age)


def main():
    problem, detail = diagnose()
    if "--status" in sys.argv:
        print("watchdog: %s - %s" % (problem or "OK", detail))
        return 0

    if not problem:
        print("watchdog OK - %s" % detail, flush=True)
        return 0

    msg = ("SUPERVISOR DOWN - %s (%s). No monitoring until it restarts."
           % (problem, detail))
    print(msg, flush=True)

    if recently_acted():
        telegram.Telegram().send(msg + "\nAlready restarted within the last "
                                 "%d min - NOT retrying, needs a look."
                                 % RESTART_COOLDOWN_MIN)
        return 1

    mark_acted()
    try:
        subprocess.check_call(["powershell", "-NoProfile", "-Command",
                               "Start-ScheduledTask -TaskName '%s'" % TASK])
        telegram.Telegram().send(msg + "\nRestarted scheduled task '%s'." % TASK)
    except Exception as e:
        telegram.Telegram().send(msg + "\nRestart FAILED: %s - intervene." % e)
        return 2
    return 1


if __name__ == "__main__":
    sys.exit(main())
