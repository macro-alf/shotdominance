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

CP = re.compile(r"cp[0-9]+ no signal")
SIG = re.compile(r">>> SIGNAL")
LEAD = re.compile(r"leading\)")
NA = re.compile(r"shots=n/a")
ROW = re.compile(r"[0-9]+' fav=")
NL = chr(10)


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
    lines.append("day          cps  sig   rate   feed-gaps")
    tot_c = tot_s = 0
    recent = []
    for p in logs:
        day = os.path.basename(p)[8:18]
        cps, sigs, _lead, rows, missing = scan(p)
        if not cps:
            continue
        tot_c += cps
        tot_s += sigs
        recent.append((day, cps, sigs))
        gap = (100 * missing // rows) if rows else 0
        lines.append("%s %4d %4d %5.1f%% %6d%%"
                     % (day, cps, sigs, 100.0 * sigs / cps, gap))

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
