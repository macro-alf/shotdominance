"""Sleep the PC at night - but never while the monitor is working.

daily.py suspends only at the END of a day it actually monitored. On a blank
day it returns early ("leaving the PC awake, exiting") and nothing sleeps the
machine - 21-24 Sep 2026 it stayed awake four nights running. The idle sleep
timeout on AC is 0 (never), so nothing else will do it either.

Calls SetSuspendState directly rather than going through daily.suspend(),
whose END_ACTION defaults to "restart" - a missing env var should not turn
bedtime into a reboot.

Registered as the InplaySleep task: 23:30, retrying every 15 min until 02:00.
"""
import datetime as dt
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
HEARTBEAT = os.path.join(HERE, "logs", "heartbeat.txt")
LOG = os.path.join(HERE, "logs", "sleeper.log")
STALE_MIN = int(os.getenv("SLEEPER_STALE_MIN", "25"))
BUSY = ("waiting-for-launch", "planning", "monitoring", "ending")


def log(msg):
    line = "%s %s" % (dt.datetime.now().isoformat(timespec="seconds"), msg)
    print(line, flush=True)
    try:
        with open(LOG, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except Exception as e:
        print("  ! sleeper log write failed: %s" % e, flush=True)


def read_beat():
    """(when, state) from the heartbeat daily.py writes, or (None, None)."""
    try:
        raw = open(HEARTBEAT, encoding="utf-8").read().split()
        return dt.datetime.fromisoformat(raw[0]), raw[1]
    except Exception:
        return None, None


def main():
    when, state = read_beat()
    if when is None:
        log("no readable heartbeat - nothing is supervising, sleeping")
    else:
        age = (dt.datetime.now() - when).total_seconds() / 60.0
        if state in BUSY and age <= STALE_MIN:
            log("HOLD - monitor is %s (%.0f min old); daily.py suspends itself"
                % (state, age))
            return
        log("state=%s, %.0f min old - safe to sleep" % (state, age))
    if "--dry-run" in sys.argv:
        log("--dry-run set, not sleeping")
        return
    subprocess.call(["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"])


if __name__ == "__main__":
    main()
