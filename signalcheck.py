#!/usr/bin/env python3
"""Summarise recent signal activity and send it to Telegram.

    python signalcheck.py             # summarise and send
    python signalcheck.py --print     # print only, send nothing
    python signalcheck.py --days 10

Exists because a signal drought is hard to judge from any single evening. On
2026-08-22, 127 checkpoints produced nothing, which felt broken but sat at about
the 1-in-30 end of normal for a 2.8%/checkpoint fire rate. The question is only
answerable across days, so this counts them.

Reads the monitor logs - no API calls, no quota cost.
"""
import glob
import os
import re
import sys

CP = re.compile(r"cp[0-9]+ (?:no signal|not yet)")
ROWPAT = re.compile(r"^\s+(?P<m>.+?)\s+(?P<min>\d+)' fav=(?P<f>\S.*?)\s+xg=")
SIG = re.compile(r">>> SIGNAL")
LEAD = re.compile(r"leading\)")
NA = re.compile(r"shots=n/a")
ROW = re.compile(r"[0-9]+' fav=")
NL = chr(10)


def feed_lateness(path):
    """Per fixture, the minute at which shot statistics FIRST appear.

    This is the number that decides whether the provider is good enough. A feed
    that publishes nothing until minute 45 destroys the 45' checkpoint outright,
    and no rule change can recover it - there is simply no data. On 2026-08-23
    two of three watched fixtures reported nothing until 45' and 47'.

    A fixture whose stats start after minute 25 cannot support even the
    MIN_WINDOW baseline for a 45' checkpoint, so it is counted as lost.
    """
    first = {}
    for line in open(path, encoding="utf-8", errors="replace"):
        g = ROWPAT.match(line)
        if not g:
            continue
        key = re.sub(r"\s*\d+-\d+\s*", " v ", g["m"].strip())
        m = int(g["min"])
        d = first.setdefault(key, None)
        if d is None and "shots=n/a" not in line:
            first[key] = m
    starts = [v for v in first.values() if v is not None]
    lost = sum(1 for v in first.values() if v is None or v > 25)
    return len(first), starts, lost


def scan(path):
    cps = sigs = leading = rows = missing = 0
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if CP.search(line):
                cps += 1
            if SIG.search(line):
                sigs += 1
                cps += 1                      # a fired checkpoint is still one
            if LEAD.search(line):
                leading += 1
            if ROW.search(line):
                rows += 1
                if NA.search(line):
                    missing += 1
    return cps, sigs, leading, rows, missing


def main():
    days = 10
    if "--days" in sys.argv:
        days = int(sys.argv[sys.argv.index("--days") + 1])
    logs = sorted(glob.glob(os.path.join("logs", "monitor-*.log")))[-days:]

    lines = ["Signal check - recent activity", ""]
    lines.append("day          cps  sig   rate  gaps  stats-from  lost")
    tot_c = tot_s = 0
    recent = []
    late_total = [0]
    fix_total = [0]
    for p in logs:
        day = os.path.basename(p)[8:18]
        cps, sigs, _lead, rows, missing = scan(p)
        if not cps:
            continue
        tot_c += cps
        tot_s += sigs
        recent.append((day, cps, sigs))
        gap = (100 * missing // rows) if rows else 0
        nfix, starts, lost = feed_lateness(p)
        med = sorted(starts)[len(starts) // 2] if starts else 0
        lost_pct = (100 * lost // nfix) if nfix else 0
        late_total[0] += lost
        fix_total[0] += nfix
        lines.append("%s %4d %4d %5.1f%% %4d%% %9s %4d%%"
                     % (day, cps, sigs, 100.0 * sigs / cps, gap,
                        ("%d'" % med) if med else "-", lost_pct))

    if not tot_c:
        lines.append("no checkpoints found in the logs")
    else:
        rate = 100.0 * tot_s / tot_c
        lines += ["", "overall %d signals from %d checkpoints (%.1f%%)"
                  % (tot_s, tot_c, rate)]
        last3 = recent[-3:]
        c3 = sum(c for _d, c, _s in last3)
        s3 = sum(s for _d, _c, s in last3)
        if c3:
            lines.append("last 3 days: %d from %d (%.1f%%)"
                         % (s3, c3, 100.0 * s3 / c3))
            if s3 == 0 and c3 >= 60:
                lines += ["",
                          "STILL DRY over %d checkpoints. Worth splitting the "
                          "cause: how many checkpoints are blocked by feed "
                          "lateness vs genuinely failing the metrics. Do not "
                          "loosen thresholds on this little data." % c3]
    if fix_total[0]:
        pct = 100 * late_total[0] // fix_total[0]
        lines += ["", "FEED: %d%% of watched fixtures publish no stats before "
                  "minute 25, so their 45' checkpoint cannot be judged at all."
                  % pct]
        if pct >= 35:
            lines += ["",
                      "THAT IS THE BINDING CONSTRAINT, NOT THE RULE. No rule "
                      "change recovers a checkpoint with no data behind it. "
                      "Time to price up another stats provider - see TODO.md."]

    text = NL.join(lines)
    print(text)
    if "--print" not in sys.argv:
        from shotdominance import telegram
        tg = telegram.Telegram()
        if not tg.enabled:
            print("[telegram not configured - not sent]")
            return 1
        tg.send(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
