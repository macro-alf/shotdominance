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
LOGFILE = os.path.join("logs", "watchdog.log")
TASK = os.getenv("MONITOR_TASK", "InplayMonitor")

# daily.py beats at least every 10 minutes while waiting and every 5 while
# supervising, so 25 minutes of silence is unambiguous rather than a slow poll.
STALE_MIN = int(os.getenv("WATCHDOG_STALE_MIN", "25"))
# Only act inside the window where the supervisor is expected to be up. Outside
# it the PC is usually asleep and this task is not running anyway.
#
# ACTIVE_FROM MUST BE LATER THAN THE InplayMonitor START TIME. This machine is
# not reliably awake before 09:30, so the supervisor is scheduled for 09:45 and
# this sits at 10:00 - otherwise every morning between the trigger and the PC
# actually waking would read as "supervisor never started today" and fire a
# false alarm. If you move the InplayMonitor schedule, move this with it.
ACTIVE_FROM = int(os.getenv("WATCHDOG_ACTIVE_FROM", "10"))
ACTIVE_TO = int(os.getenv("WATCHDOG_ACTIVE_TO", "1"))     # 10:00 -> 01:00 next day
RESTART_COOLDOWN_MIN = int(os.getenv("WATCHDOG_COOLDOWN_MIN", "60"))
OK_STATES = ("finished", "aborted")


def log(msg):
    """Every run leaves a trace. A scheduled run that fails silently is a safety
    net you only discover is missing when you need it: on 2026-08-22 the task
    detected a missed supervisor start, then terminated without restarting
    anything and without writing a word, and the whole 61-fixture Saturday was
    saved only because a human happened to look."""
    line = "%s %s" % (dt.datetime.now().isoformat(timespec="seconds"), msg)
    print(line, flush=True)
    try:
        os.makedirs("logs", exist_ok=True)
        with open(LOGFILE, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except Exception:
        pass


def read_heartbeat():
    """-> (age_minutes, state, date) or (None, None, None) when unreadable."""
    try:
        with open(HEARTBEAT, encoding="utf-8") as fh:
            stamp, _, state = fh.read().strip().partition(" ")
        when = dt.datetime.fromisoformat(stamp)
        age = (dt.datetime.now() - when)
        return age.total_seconds() / 60.0, (state or "unknown").strip(), when.date()
    except Exception:
        return None, None, None


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


def diagnose(now=None):
    """-> (problem_or_None, detail). Pure: makes no changes, sends nothing."""
    now = now or dt.datetime.now()
    age, state, when = read_heartbeat()
    if not in_active_window(now):
        return None, "outside the active window"
    if age is None:
        return "no heartbeat", "logs/heartbeat.txt missing or unreadable"
    if state in OK_STATES:
        # A deliberate stop is fine - but only for TODAY. Yesterday's clean
        # 'finished' sitting there during the active window means the
        # supervisor never started this morning, which is exactly what happened
        # on 2026-08-18: the 08:00 task missed its run while the PC slept, the
        # heartbeat still read 'finished' from 23:25 the night before, and this
        # watchdog stayed silent because the state looked deliberate.
        if when < now.date() and now.hour >= ACTIVE_FROM:
            return ("supervisor never started today",
                    "last beat %s on %s, %.0f min ago" % (state, when, age))
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
        log("OK - %s" % detail)
        return 0

    tg = telegram.Telegram()
    if not tg.enabled:
        log("WARNING: telegram not configured in this environment - the alert "
            "below reaches nobody")

    msg = ("SUPERVISOR DOWN - %s (%s). No monitoring until it restarts."
           % (problem, detail))
    log(msg)

    if recently_acted():
        log("already acted within %d min - not retrying" % RESTART_COOLDOWN_MIN)
        tg.send(msg + "\nAlready restarted within the last %d min - NOT "
                "retrying, needs a look." % RESTART_COOLDOWN_MIN)
        return 0

    mark_acted()
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-Command",
                            "Start-ScheduledTask -TaskName '%s'" % TASK],
                           capture_output=True, text=True, timeout=120)
        log("restart '%s' rc=%s %s%s" % (TASK, r.returncode,
                                         (r.stdout or "").strip(),
                                         (r.stderr or "").strip()))
        if r.returncode != 0:
            raise RuntimeError((r.stderr or "").strip() or "rc=%s" % r.returncode)
        tg.send(msg + "\nRestarted scheduled task '%s'." % TASK)
    except Exception as e:
        log("RESTART FAILED: %s" % e)
        tg.send(msg + "\nRestart FAILED: %s - intervene." % e)
        return 2
    return 0


if __name__ == "__main__":
    # Never die silently - a traceback that nobody sees is the same as no
    # watchdog at all.
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception:
        import traceback
        log("CRASHED\n%s" % traceback.format_exc())
        sys.exit(3)
