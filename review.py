#!/usr/bin/env python3
"""End-of-day review of monitor logs. Reads a WHOLE DIRECTORY so evidence
accumulates - one day cannot distinguish "the filter is too tight" from
"yesterday had no dominant favourites".

    python review.py                 # ./logs, all *.log
    python review.py --dir logs --days 7
    python review.py --top 15

Nothing is inferred that the log does not contain. Every console line carries
value[required]/opponent for all four metrics, so the binding constraint is
RECOMPUTED here rather than guessed: a metric can fail on the absolute bar, on
the dominance test, or both, and those need different fixes.

Writes review_rows.csv - one row per evaluated checkpoint - for pivoting.
"""
from __future__ import annotations
import os, re, csv, sys, glob, collections

try:                       # never die printing an accented (or mangled) team
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # name on Windows
except Exception:
    pass

DOM_RATIO = float(os.getenv("DOM_RATIO", "0.50"))
NEED = 2
FLOOR, CEIL = 1.75, 4.00

ROW = re.compile(
    r"^\s+(?P<match>.+?)\s+(?P<min>\d+)'\s+fav=(?P<fav>\S.*?)\s+"
    r"(?P<stats>xg=\S+\s+shots=\S+\s+sot=\S+\s+box=\S+)\s+"
    r"vol=(?P<vol>\d)/\d\s+mom=(?P<mom>\d)/\d(?P<ap>[~ *])\s*"
    r"conv=(?P<conv>\d+)\s+(?:pm=(?P<pm>[0-9.]+)\s+)?odds=(?P<odds>\S+)\s+cp=(?P<cp>\S+)\s*$")
LEAD = re.compile(r"^\s+(?P<match>.+?)\s+(?P<min>\d+)'\s+fav=(?P<fav>\S.*?)\s+"
                  r"(?P<stats>xg=\S+.*?)\s+cp=(?P<cp>\S+)\s+\(leading\)\s*$")
METRIC = re.compile(r"(xg|shots|sot|box)=(?:n/a|([0-9.]+)\[([0-9.]+)\]/(\?|[0-9.]+))")
NOSIG = re.compile(r"^\s+cp(?P<cp>\d+) no signal: (?P<why>.+?)\s*$")
SUPPR = re.compile(r"^\s+cp(?P<cp>\d+): signal suppressed")
SIGNAL = re.compile(r">>> SIGNAL (?P<rest>.+?) conv=(?P<conv>\d+) stake=(?P<stake>[\d.]+) \((?P<basis>.+)\)")
BETLOG = re.compile(r">>> BET LOGGED (?P<m>.+?) stake (?P<s>[\d.]+) @ (?P<p>[\d.]+)")
POLL = re.compile(r"^poll: (?P<live>\d+) live, (?P<watch>\d+) watched, (?P<req>\d+) requests total(?P<tail>.*)$")
ODDSL = re.compile(r"^\s+odds: (?P<n>\d+) priced \((?P<b>\d+) blocked, (?P<s>\d+) suspended")
RETRY = re.compile(r"rate limited, backing off")
APIERR = re.compile(r"! API errors:")
BASIS0 = re.compile(r"0 goals: volume AND momentum")
BASISN = re.compile(r"scored (?P<g>\d+): momentum\((?P<a>yes|no)\) OR (?P<m>\d+)x cumulative\((?P<b>yes|no)\)")


def parse_stats(blob):
    """-> {key: (value, required, opp_or_None)} ; missing value -> None entry."""
    out = {}
    for m in METRIC.finditer(blob):
        k, v, need, opp = m.group(1), m.group(2), m.group(3), m.group(4)
        if v is None:
            out[k] = None
        else:
            out[k] = (float(v), float(need),
                      None if opp == "?" else float(opp))
    return out


def classify(stats):
    """Per metric: pass / abs / dom / both / opp_missing / value_missing."""
    verdict, eff = {}, {}
    for k in ("xg", "shots", "sot", "box"):
        s = stats.get(k)
        if s is None:
            verdict[k] = "value_missing"; eff[k] = 0.0; continue
        v, need, opp = s
        abs_ok = v >= need
        if opp is None:
            verdict[k] = "opp_missing"; eff[k] = 0.0; continue
        dom_ok = v > 0 and (opp / v) <= DOM_RATIO
        eff[k] = (v / need) if (dom_ok and need > 0) else 0.0
        if abs_ok and dom_ok:
            verdict[k] = "pass"
        elif abs_ok and not dom_ok:
            verdict[k] = "dom"
        elif dom_ok and not abs_ok:
            verdict[k] = "abs"
        else:
            verdict[k] = "both"
    return verdict, eff


def closeness(eff):
    """With NEED=2, the binding number is the 2nd-best effective ratio."""
    return sorted(eff.values(), reverse=True)[NEED - 1] if len(eff) >= NEED else 0.0


def load(paths):
    rows, events = [], collections.Counter()
    nosig, signals, bets, polls = [], [], [], []
    pending = {}
    for path in paths:
        day = os.path.basename(path)
        with open(path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.rstrip("\n")
                if RETRY.search(line): events["rate_limit_retries"] += 1; continue
                if APIERR.search(line): events["api_error_lines"] += 1; continue
                mo = POLL.match(line)
                if mo:
                    polls.append((day, int(mo.group("live")), int(mo.group("watch")),
                                  int(mo.group("req"))))
                    if "xG NOT SEEN" in mo.group("tail"): events["polls_without_xg"] += 1
                    continue
                mo = ODDSL.match(line)
                if mo:
                    events["odds_blocked"] += int(mo.group("b"))
                    events["odds_suspended"] += int(mo.group("s"))
                    continue
                mo = SIGNAL.search(line)
                if mo:
                    signals.append((day, mo.group("rest").strip(), int(mo.group("conv")),
                                    float(mo.group("stake")), mo.group("basis")))
                    continue
                mo = BETLOG.search(line)
                if mo:
                    bets.append((day, mo.group("m").strip(), float(mo.group("s")),
                                 float(mo.group("p"))))
                    continue
                if SUPPR.match(line): events["suppressed_after_bet"] += 1; continue
                mo = NOSIG.match(line)
                if mo:
                    nosig.append((day, int(mo.group("cp")), mo.group("why"), pending.get(day)))
                    continue
                mo = LEAD.match(line)
                if mo:
                    events["rows_favourite_leading"] += 1; continue
                mo = ROW.match(line)
                if not mo:
                    continue
                stats = parse_stats(mo.group("stats"))
                verdict, eff = classify(stats)
                odds = mo.group("odds")
                rec = dict(day=day, match=mo.group("match").strip(),
                           minute=int(mo.group("min")), fav=mo.group("fav").strip(),
                           vol=int(mo.group("vol")), mom=int(mo.group("mom")),
                           approx=(mo.group("ap") == "~"), conv=int(mo.group("conv")),
                           odds=(None if odds == "n/a" else float(odds)),
                           pm=(float(mo.group("pm")) if mo.groupdict().get("pm") else None),
                           cp=(None if mo.group("cp") == "None" else int(mo.group("cp"))),
                           close=round(closeness(eff), 3))
                for k in ("xg", "shots", "sot", "box"):
                    s = stats.get(k)
                    rec[k] = None if s is None else s[0]
                    rec[k + "_need"] = None if s is None else s[1]
                    rec[k + "_opp"] = None if (s is None or s[2] is None) else s[2]
                    rec[k + "_why"] = verdict[k]
                rows.append(rec)
                pending[day] = rec
    return rows, nosig, signals, bets, polls, events


# --- report -----------------------------------------------------------------
def bar(n, total, width=28):
    if not total:
        return ""
    return "#" * max(0, int(round(width * n / total)))


def section(t):
    print("\n" + "=" * 74); print(t); print("=" * 74)


def report(rows, nosig, signals, bets, polls, events, top):
    cps = [r for r in rows if r["cp"] is not None]
    section("COVERAGE")
    days = sorted({r["day"] for r in rows})
    print("  log files            %d  (%s)" % (len(days), ", ".join(days[:6]) +
                                               (" ..." if len(days) > 6 else "")))
    print("  match-lines parsed   %d" % len(rows))
    print("  checkpoint evals     %d" % len(cps))
    print("  distinct matches     %d" % len({(r["day"], r["match"]) for r in rows}))
    print("  signals fired        %d" % len(signals))
    print("  bets logged          %d" % len(bets))
    if polls:
        print("  polls                %d, peak watched %d, requests high-water %d"
              % (len(polls), max(p[2] for p in polls), max(p[3] for p in polls)))

    section("1. CLOSEST TO A TRIGGER  (best moment per match)")
    best = {}
    for r in cps or rows:
        k = (r["day"], r["match"])
        cur = best.get(k)
        if cur is None or (r["vol"] + r["mom"], r["close"], r["conv"]) > \
                          (cur["vol"] + cur["mom"], cur["close"], cur["conv"]):
            best[k] = r
    ranked = sorted(best.values(), key=lambda r: (r["vol"] + r["mom"], r["close"],
                                                  r["conv"]), reverse=True)[:top]
    if not ranked:
        print("  nothing evaluated at a checkpoint")
    else:
        print("  %-32s %4s %4s %4s %5s %6s %6s  %s"
              % ("match", "min", "vol", "mom", "conv", "close", "odds", "binding"))
        for r in ranked:
            fails = [k for k in ("xg", "shots", "sot", "box")
                     if r[k + "_why"] not in ("pass",)]
            why = collections.Counter(r[k + "_why"] for k in fails)
            print("  %-32s %4d %3d/4 %3d/4 %5d %6.2f %6s  %s%s"
                  % (r["match"][:32], r["minute"], r["vol"], r["mom"], r["conv"],
                     r["close"], ("%.2f" % r["odds"]) if r["odds"] else "n/a",
                     ", ".join("%s x%d" % (k, v) for k, v in why.most_common()) or "-",
                     "  [~approx]" if r["approx"] else ""))
        print("\n  close = 2nd-best ratio to threshold among metrics that also pass")
        print("  dominance. 1.00 means it would have met the 2-of-4 volume test.")

    section("2. WHY METRICS FAILED  (checkpoint evaluations only)")
    tally = collections.Counter()
    per_metric = collections.defaultdict(collections.Counter)
    for r in cps:
        for k in ("xg", "shots", "sot", "box"):
            tally[r[k + "_why"]] += 1
            per_metric[k][r[k + "_why"]] += 1
    tot = sum(tally.values()) or 1
    labels = {"pass": "passed both tests", "abs": "below absolute bar only",
              "dom": "ABOVE bar but opponent >%.0f%% (dominance killed it)" % (DOM_RATIO * 100),
              "both": "below bar AND not dominant",
              "opp_missing": "opponent stat missing - cannot judge",
              "value_missing": "our stat missing (xG null)"}
    for k, n in tally.most_common():
        print("  %-46s %5d  %4.0f%%  %s" % (labels.get(k, k), n, 100*n/tot, bar(n, tot)))
    print("\n  by metric:")
    print("  %-8s %7s %7s %7s %7s %7s" % ("", "pass", "abs", "dom", "both", "missing"))
    for k in ("xg", "shots", "sot", "box"):
        c = per_metric[k]
        print("  %-8s %7d %7d %7d %7d %7d" % (k, c["pass"], c["abs"], c["dom"],
              c["both"], c["opp_missing"] + c["value_missing"]))
    dom_only = tally["dom"]
    if dom_only:
        print("\n  %d metric-checks cleared the absolute bar and were rejected purely"
              % dom_only)
        print("  on dominance. That is the %.0f%% test doing the filtering, not the"
              % (DOM_RATIO * 100))
        print("  thresholds - loosen DOM_RATIO before touching BASE45 if this is high.")

    section("3. DATA QUALITY")
    n = len(rows) or 1
    xg_null = sum(1 for r in rows if r["xg"] is None)
    opp_null = sum(1 for r in rows if any(r[k + "_opp"] is None for k in
                                          ("shots", "sot", "box")))
    odds_null = sum(1 for r in rows if r["odds"] is None)
    approx = sum(1 for r in rows if r["approx"])
    zeros = sum(1 for r in rows if r["minute"] > 40 and (r["shots"] or 0) == 0
                and (r["sot"] or 0) == 0 and (r["box"] or 0) == 0)
    for lab, v in [("rows with xG null", xg_null),
                   ("rows with an opponent stat missing", opp_null),
                   ("rows with no live price (odds=n/a)", odds_null),
                   ("rows with incomplete momentum window (~)", approx),
                   ("rows all-zero after minute 40 (suspect feed)", zeros)]:
        print("  %-46s %5d  %4.0f%%  %s" % (lab, v, 100*v/n, bar(v, n)))
    for k, v in sorted(events.items()):
        print("  %-46s %5d" % (k.replace("_", " "), v))
    if zeros:
        print("\n  All-zero rows after minute 40 usually mean a rate-limited stats")
        print("  call returned an empty response, which the parser reads as 0 shots.")
        print("  Those rows understate dominance and can suppress real signals.")

    section("4. GATE CENSUS  (from 'no signal' lines)")
    reasons = collections.Counter()
    branch = collections.Counter()
    for day, cp, why, _ in nosig:
        if "price" in why and "outside" in why: reasons["price outside band"] += 1
        if "window incomplete" in why: reasons["momentum window incomplete"] += 1
        if "no baseline since goal" in why: reasons["no goal baseline"] += 1
        m = re.search(r"vol (\d)/\d mom (\d)/\d", why)
        if m:
            v, mm = int(m.group(1)), int(m.group(2))
            if v < NEED and mm < NEED: reasons["volume AND momentum short"] += 1
            elif v < NEED: reasons["volume short only"] += 1
            elif mm < NEED: reasons["momentum short only"] += 1
        if BASIS0.search(why): branch["0-0 branch (volume AND momentum)"] += 1
        b = BASISN.search(why)
        if b:
            branch["scored %s: momentum=%s cumulative=%s" %
                   (b.group("g"), b.group("a"), b.group("b"))] += 1
    tot = sum(reasons.values()) or 1
    for k, v in reasons.most_common():
        print("  %-46s %5d  %4.0f%%  %s" % (k, v, 100*v/tot, bar(v, tot)))
    print("\n  branch in force at rejected checkpoints:")
    for k, v in branch.most_common():
        print("    %-56s %5d" % (k, v))
    if signals:
        print("\n  signals that fired:")
        for day, rest, conv, stake, basis in signals:
            print("    %-40s conv=%d stake=%.0f  [%s]" % (rest[:40], conv, stake, basis))
    else:
        print("\n  no signals fired in this period.")

    section("5. CONVICTION AND PRICE")
    hist = collections.Counter(min(9, r["conv"] // 10) for r in cps)
    for b in range(10):
        lo = b * 10
        print("  conv %3d-%3d %5d  %s" % (lo, lo + 9, hist[b], bar(hist[b], len(cps) or 1)))
    prices = [r["odds"] for r in rows if r["odds"]]
    if prices:
        below = sum(1 for p in prices if p < FLOOR)
        inband = sum(1 for p in prices if FLOOR <= p <= CEIL)
        above = sum(1 for p in prices if p > CEIL)
        t = len(prices)
        print("\n  live prices seen      %d (plus %d rows with none)" % (t, odds_null))
        print("  below %.2f floor      %5d  %4.0f%%" % (FLOOR, below, 100*below/t))
        print("  inside band          %5d  %4.0f%%" % (inband, 100*inband/t))
        print("  above %.2f ceiling    %5d  %4.0f%%" % (CEIL, above, 100*above/t))
        print("  median price          %.2f" % sorted(prices)[t//2])
    pms = [r["pm"] for r in rows if r.get("pm")]
    if pms:
        pms.sort()
        print("\n  pre-match favourite prices seen (the %.2f-%.2f gate):"
              % (float(os.getenv("MIN_ODDS", "1.30")), float(os.getenv("MAX_ODDS", "2.25"))))
        for lo, hi in ((1.30, 1.60), (1.60, 1.95), (1.95, 2.25)):
            n = sum(1 for p in pms if lo <= p < hi)
            print("    %.2f - %.2f  %5d  %4.0f%%  %s"
                  % (lo, hi, n, 100*n/len(pms), bar(n, len(pms))))
        wide = sum(1 for p in pms if p > 1.95)
        print("    median %.2f | %d rows (%.0f%%) come from the band ABOVE 1.95 -"
              % (pms[len(pms)//2], wide, 100*wide/len(pms)))
        print("    that is what widening the cap to 2.25 actually bought you.")
    else:
        print("\n  no pre-match prices parsed yet (no pm= rows in these logs).")


def blotter(path="blotter.csv"):
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    if not rows:
        return
    section("6. BLOTTER")
    done = [r for r in rows if r.get("status") in ("won", "lost")]
    print("  bets logged %d  (open %d, settled %d)"
          % (len(rows), len(rows) - len(done), len(done)))
    if done:
        pnl = sum(float(r["pnl"] or 0) for r in done)
        staked = sum(float(r["stake"] or 0) for r in done)
        wins = sum(1 for r in done if r["status"] == "won")
        print("  win rate %.0f%%  staked %.0f  P&L %+.2f  ROI %+.1f%%"
              % (100*wins/len(done), staked, pnl, 100*pnl/staked if staked else 0))
        buckets = collections.defaultdict(list)
        for r in done:
            try: buckets[int(float(r["conviction"]) // 10) * 10].append(r)
            except (TypeError, ValueError): pass
        if buckets:
            print("\n  by conviction bucket (this is the test that earns a bigger multiplier):")
            print("  %8s %6s %8s %10s" % ("bucket", "bets", "win%", "ROI"))
            for b in sorted(buckets):
                g = buckets[b]
                st = sum(float(r["stake"] or 0) for r in g)
                pl = sum(float(r["pnl"] or 0) for r in g)
                w = sum(1 for r in g if r["status"] == "won")
                print("  %6d-%d %6d %7.0f%% %9.1f%%" % (b, b+9, len(g), 100*w/len(g),
                                                        100*pl/st if st else 0))
            print("\n  Fewer than ~200 settled bets and these buckets are noise.")


def main():
    a = sys.argv[1:]
    d = a[a.index("--dir") + 1] if "--dir" in a else "logs"
    top = int(a[a.index("--top") + 1]) if "--top" in a else 10
    paths = sorted(glob.glob(os.path.join(d, "monitor-*.log"))) or sorted(glob.glob(os.path.join(d, "*.log")))
    if "--days" in a:
        paths = paths[-int(a[a.index("--days") + 1]):]
    if not paths:
        sys.exit("no *.log files in %s" % d)
    rows, nosig, signals, bets, polls, events = load(paths)
    if not rows:
        sys.exit("parsed 0 match-lines - is this a monitor log?")
    report(rows, nosig, signals, bets, polls, events, top)
    blotter(a[a.index("--blotter") + 1] if "--blotter" in a else "blotter.csv")
    cols = list(rows[0].keys())
    with open("review_rows.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols); w.writeheader(); w.writerows(rows)
    print("\n\nwrote review_rows.csv (%d rows) for pivoting." % len(rows))


if __name__ == "__main__":
    main()
