#!/usr/bin/env python3
"""Daily supervisor. Start it once in the morning; it does the rest.

    python daily.py            # arm for today
    python daily.py --dry-run  # print the plan and exit (costs 2 requests)
    python daily.py --no-sleep # run the full day but never suspend the PC

WHAT IT DOES
  1. Reads today's schedule for the tracked competitions (ONE request).
  2. Sleeps until LEAD minutes BEFORE the first kickoff, then launches
     monitor.py as a child process, echoing its output to the console and to
     logs/monitor-YYYY-MM-DD.log.
  3. From POLL_FROM_MIN minutes after the LAST kickoff it re-checks the schedule
     until every tracked fixture reports a finished status.
  4. Waits TAIL minutes, stops the monitor, runs endday.py, and (unless
     --no-sleep) suspends the PC.

WHY IT STARTS BEFORE THE FIRST KICKOFF, NOT AT IT
  The 45' checkpoint needs a snapshot from WINDOW minutes earlier to difference
  against. A monitor that starts at kickoff is fine; one that starts late marks
  momentum "[from kickoff]" (no evidence). LEAD defaults to 15.

This supervisor also tees its own progress to logs/daily-YYYY-MM-DD.log, which
endday.py reads to reconstruct the day.
"""
import datetime as dt
import os
import subprocess
import sys
import threading
import time

try:                       # force UTF-8 stdout (accented team names, Windows)
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from shotdominance import apifootball, config, telegram

# ensure the monitor and endday children we launch also emit UTF-8
os.environ["PYTHONUTF8"] = "1"
os.environ.setdefault("PYTHONIOENCODING", "utf-8")

LEAD_MIN = int(os.getenv("LEAD_MIN", "15"))
TAIL_MIN = int(os.getenv("TAIL_MIN", "15"))
POLL_FROM_MIN = int(os.getenv("POLL_FROM_MIN", "100"))
HARD_STOP_MIN = int(os.getenv("HARD_STOP_MIN", "210"))
CHECK_EVERY = 300
DAILY_BUDGET = int(os.getenv("DAILY_BUDGET", "7500"))
QUOTA_RESERVE = int(os.getenv("QUOTA_RESERVE", "600"))
BAND_SHARE = float(os.getenv("BAND_SHARE", "0.45"))
POLL_MIN, POLL_MAX = 60, 300
# Minutes after kickoff over which a fixture costs a statistics call. The lower
# bound IS the engine's recording gate - derive it so the two cannot drift (it
# was a stale literal 30 while the engine had always recorded from 15).
WATCH_FROM = config.CHECKPOINTS[0] - config.WINDOW - config.RECORD_LEAD
WATCH_TO = 100
TZNAME = os.getenv("TZNAME", "Europe/Rome")
MONITOR = os.getenv("MONITOR_SCRIPT", "monitor.py")
DONE_STATUS = {"FT", "AET", "PEN", "PST", "CANC", "ABD", "AWD", "WO"}

_api = None
_tg = None
_daily_log = None


def pace(pending, start_at, end_est):
    """Choose POLL so the day's requests fit the daily quota.

    Cost per poll is 2 fixed calls (/odds/live, /fixtures?live=all) plus one
    statistics call per fixture currently between minute 30 and full time whose
    favourite sits inside the pre-match band.

        requests = (2*span + BAND_SHARE*watched_minutes) / POLL_minutes + N

    where N is the one-off pre-match odds lookup each fixture costs.
    """
    span_min = max((end_est - start_at) / 60.0, 60.0)
    watched_min = len(pending) * (WATCH_TO - WATCH_FROM)
    numerator = 2.0 * span_min + BAND_SHARE * watched_min
    budget = max(DAILY_BUDGET - QUOTA_RESERVE - len(pending), 1)
    need_s = (numerator / budget) * 60.0
    poll = int(min(max(round(need_s / 15.0) * 15, POLL_MIN), POLL_MAX))
    est = int(numerator / (poll / 60.0) + len(pending))
    peak = 0
    for ts, _, _ in pending:
        n = sum(1 for o, _, _ in pending
                if o + WATCH_FROM * 60 <= ts + WATCH_FROM * 60 <= o + WATCH_TO * 60)
        peak = max(peak, n)
    return poll, est, span_min, peak


def clock(ts):
    return dt.datetime.fromtimestamp(ts).strftime("%H:%M")


def say(msg):
    line = "[daily %s] %s" % (dt.datetime.now().strftime("%H:%M:%S"), msg)
    print(line, flush=True)
    if _daily_log:
        try:
            _daily_log.write(line + "\n")
            _daily_log.flush()
        except Exception:
            pass


def todays_fixtures(ids):
    day = dt.datetime.now().strftime("%Y-%m-%d")
    rows = _api.get("/fixtures", date=day, timezone=TZNAME)
    out = []
    for fx in rows:
        if ids and (fx.get("league") or {}).get("id") not in ids:
            continue
        f = fx.get("fixture") or {}
        ts, st = f.get("timestamp"), (f.get("status") or {}).get("short")
        if ts:
            out.append((int(ts), st, fx))
    return sorted(out, key=lambda x: x[0])


def wait_until(target, label):
    while True:
        left = target - time.time()
        if left <= 0:
            return
        say("%s in %d min (at %s)" % (label, int(left // 60) + 1, clock(target)))
        time.sleep(min(left, 600))


def pump(proc, path):
    """Echo the child's output to console and log without losing either."""
    with open(path, "a", encoding="utf-8", buffering=1) as fh:
        for line in iter(proc.stdout.readline, ""):
            sys.stdout.write(line)
            sys.stdout.flush()
            fh.write(line)


def suspend():
    action = os.getenv("END_ACTION", "restart").lower()
    say("END_ACTION=%s" % action)
    time.sleep(2)
    if action == "sleep":
        subprocess.call(["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"])
    else:
        subprocess.call(["shutdown", "/g", "/t", "60", "/c",
                         "In-play monitor finished for the day - restarting."])


def main():
    global _api, _tg, _daily_log
    dry = "--dry-run" in sys.argv
    no_sleep = "--no-sleep" in sys.argv
    if not config.API_KEY:
        sys.exit("APIFOOTBALL_KEY not set")

    _api = apifootball.ApiClient()
    _tg = telegram.Telegram()
    os.makedirs("logs", exist_ok=True)
    day = dt.datetime.now().strftime("%Y-%m-%d")
    _daily_log = open(os.path.join("logs", "daily-%s.log" % day), "a",
                      encoding="utf-8", buffering=1)

    say("resolving competitions")
    ids = apifootball.resolve_leagues(_api)
    sched = todays_fixtures(ids)
    pending = [x for x in sched if x[1] not in DONE_STATUS]

    say("%d tracked fixtures today, %d still to play" % (len(sched), len(pending)))
    for ts, st, fx in sched:
        t = fx["teams"]
        say("   %s  %-34s %-30s %s" % (clock(ts), t["home"]["name"] + " v " +
                                       t["away"]["name"], fx["league"]["name"], st))

    if not pending:
        say("no fixtures left to play today - leaving the PC awake, exiting")
        return

    first, last = pending[0][0], pending[-1][0]
    start_at = first - LEAD_MIN * 60
    say("first kickoff %s -> monitor starts %s (%d min lead)"
        % (clock(first), clock(start_at), LEAD_MIN))
    say("last kickoff  %s -> end-checks from %s, hard stop %s"
        % (clock(last), clock(last + POLL_FROM_MIN * 60),
           clock(last + HARD_STOP_MIN * 60)))
    say("then +%d min tail, then %s"
        % (TAIL_MIN, "NOTHING (--no-sleep)" if no_sleep else "suspend"))
    p_s, p_est, p_span, p_peak = pace(pending, start_at, last + 135 * 60)
    say("pacing: %.1fh window, %d fixtures, peak %d overlapping -> POLL=%ds, "
        "~%d of %d requests" % (p_span / 60.0, len(pending), p_peak, p_s,
                                p_est, DAILY_BUDGET))
    if dry:
        say("dry run - nothing launched")
        return

    if start_at > time.time():
        wait_until(start_at, "monitor launch")
    else:
        say("first kickoff already passed - starting now; early matches may "
            "show [from kickoff] momentum until %d min of history exists"
            % config.WINDOW)

    poll_s, est, span_min, peak = pace(pending, start_at, last + 135 * 60)
    say("pacing: %.1fh window, %d fixtures, peak %d overlapping -> POLL=%ds, "
        "~%d of %d requests" % (span_min / 60.0, len(pending), peak, poll_s,
                                est, DAILY_BUDGET))
    if est > DAILY_BUDGET - QUOTA_RESERVE:
        say("WARNING: even at POLL=%ds the day does not fit the quota" % POLL_MAX)
    os.environ["POLL_SECONDS"] = str(poll_s)

    log = os.path.join("logs", "monitor-%s.log" % day)
    say("launching %s -> %s" % (MONITOR, log))
    _tg.send("Monitor armed for today: %d fixtures, first %s, last %s."
             % (len(pending), clock(first), clock(last)))

    proc = subprocess.Popen([sys.executable, "-u", MONITOR],
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, encoding="utf-8", errors="replace")
    threading.Thread(target=pump, args=(proc, log), daemon=True).start()

    poll_from = last + POLL_FROM_MIN * 60
    hard_stop = last + HARD_STOP_MIN * 60
    try:
        while time.time() < hard_stop:
            if proc.poll() is not None:
                say("monitor exited early (code %s) - not suspending"
                    % proc.returncode)
                return
            if time.time() >= poll_from:
                rest = todays_fixtures(ids)
                unfinished = [x for x in rest if x[1] not in DONE_STATUS]
                if not unfinished:
                    say("all tracked fixtures finished")
                    break
                say("still in play: %s" % ", ".join(
                    "%s (%s)" % (x[2]["teams"]["home"]["name"], x[1])
                    for x in unfinished[:4]))
                time.sleep(CHECK_EVERY)
            else:
                time.sleep(60)
        else:
            say("hard stop reached with fixtures still open - stopping anyway")

        say("waiting %d min tail before stopping the monitor" % TAIL_MIN)
        time.sleep(TAIL_MIN * 60)
    except KeyboardInterrupt:
        say("interrupted - stopping monitor, not suspending")
        proc.terminate()
        return

    proc.terminate()
    try:
        proc.wait(timeout=30)
    except Exception:
        proc.kill()
    _tg.send("Monitor stopped for the day. Log: %s" % log)
    say("monitor stopped, log at %s" % log)
    os.system('"%s" endday.py' % sys.executable)
    say("end-of-day report step finished")
    if no_sleep:
        say("--no-sleep set, staying awake")
    else:
        suspend()


if __name__ == "__main__":
    main()
