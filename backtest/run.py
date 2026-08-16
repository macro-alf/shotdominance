"""Phase 1 runner: does shot dominance while not winning predict the result?

    python -m backtest.run --seasons 2023
    python -m backtest.run --seasons 2020,2021,2022,2023 --leagues EPL,La_liga

Writes backtest_rows.csv and prints the comparison that matters: among the SAME
situational population (pre-match favourite in band, not winning at minute m),
how do the situations that signalled compare with those that did not?

The base rate is the control. A signal that merely reproduces "favourites who
are drawing tend to win" is worth nothing; it has to beat that.
"""
import argparse
import csv
import math
import sys

from . import replay, sources


def wilson(k, n, z=1.96):
    """95% CI for a proportion. Small samples are the norm here, so Wilson
    rather than the normal approximation."""
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return ((c - half) / d, (c + half) / d)


def two_proportion_z(k1, n1, k2, n2):
    """z for H0: the two win rates are equal. None when a cell is empty."""
    if not n1 or not n2:
        return None
    p1, p2 = k1 / n1, k2 / n2
    p = (k1 + k2) / (n1 + n2)
    se = math.sqrt(p * (1 - p) * (1 / n1 + 1 / n2))
    if se == 0:
        return None
    return (p1 - p2) / se


def rate(rows):
    n = len(rows)
    k = sum(1 for r in rows if r["won"])
    lo, hi = wilson(k, n)
    return k, n, (k / n if n else 0.0), lo, hi


def line(label, rows):
    k, n, p, lo, hi = rate(rows)
    return "  %-28s %5d  %5.1f%%  [%4.1f%%, %4.1f%%]  (%d won)" % (
        label, n, 100 * p, 100 * lo, 100 * hi, k)


def report(rows, title):
    print("\n" + title)
    print("  %-28s %5s  %6s  %-16s" % ("population", "n", "win%", "95% CI"))
    fired = [r for r in rows if r["fired"]]
    quiet = [r for r in rows if not r["fired"]]
    print(line("all eligible (base rate)", rows))
    # the metric rule on its own, before the conviction floor and the
    # rising-only repeat policy - separates "does dominance predict" from
    # "does the conviction gate add anything".
    print(line("rule passed (pre-conviction)", [r for r in rows if r["rule_ok"]]))
    print(line("signalled", fired))
    print(line("did not signal", quiet))
    z = two_proportion_z(sum(1 for r in fired if r["won"]), len(fired),
                         sum(1 for r in quiet if r["won"]), len(quiet))
    if z is not None:
        _, _, pf, _, _ = rate(fired)
        _, _, pq, _, _ = rate(quiet)
        print("  lift %+.1f pp, z = %+.2f%s" % (
            100 * (pf - pq), z,
            "  (significant at 95%)" if abs(z) >= 1.96 else "  (not significant)"))


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--leagues", default=",".join(sources.LEAGUES))
    ap.add_argument("--seasons", default="2023")
    ap.add_argument("--out", default="backtest_rows.csv")
    a = ap.parse_args(argv)

    leagues = [x.strip() for x in a.leagues.split(",") if x.strip()]
    seasons = [x.strip() for x in a.seasons.split(",") if x.strip()]

    rows, skipped, unmatched, recon_fail = [], 0, 0, 0
    for season in seasons:
        for lg in leagues:
            matched, un = sources.joined(lg, season)
            unmatched += len(un)
            for i, fx in enumerate(matched, 1):
                try:
                    shots = sources.match_shots(fx["match_id"])
                except Exception as e:
                    print("  ! %s %s match %s: %s" % (lg, season, fx["match_id"], e),
                          file=sys.stderr)
                    skipped += 1
                    continue
                out = replay.replay_match(fx, shots)
                if not out:
                    skipped += 1
                for r in out:
                    r["season"], r["league"] = season, lg
                rows.extend(out)
                if i % 50 == 0:
                    print("  %s %s: %d/%d matches, %d rows"
                          % (lg, season, i, len(matched), len(rows)), flush=True)
            print("%s %s done - %d matches, %d unmatched, %d rows so far"
                  % (lg, season, len(matched), len(un), len(rows)), flush=True)

    if not rows:
        sys.exit("no rows produced")

    with open(a.out, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    print("\n%d checkpoint rows from %d fixtures (%d skipped: not in the "
          "favourite band, always leading, or reconstruction mismatch; "
          "%d unmatched on odds)"
          % (len(rows), len({r["match_id"] for r in rows}), skipped, unmatched))
    print("Rows written to %s" % a.out)

    report(rows, "ALL eligible checkpoints (favourite in band, not winning)")
    report([r for r in rows if r["state"] == "level"],
           "LEVEL - backed to WIN")
    report([r for r in rows if r["state"] == "behind"],
           "BEHIND - backed DOUBLE CHANCE (win or draw)")

    # One row per match, so the sample is independent (the checkpoint rows above
    # are not - a single match contributes up to seven of them).
    #
    # Signal group  = the FIRST checkpoint that fired, i.e. the bet the monitor
    #                 would actually have placed and then suppressed.
    # Control group = matches that never fired, taken at their first eligible
    #                 checkpoint.
    # Caveat: the two groups are therefore judged at different minutes on
    # average, so read this alongside the per-checkpoint tables above.
    per_match = {}
    for r in sorted(rows, key=lambda r: (r["match_id"], r["minute"])):
        cur = per_match.get(r["match_id"])
        if cur is None:
            per_match[r["match_id"]] = r
        elif r["fired"] and not cur["fired"]:
            per_match[r["match_id"]] = r
    report(list(per_match.values()),
           "PER MATCH - first fired checkpoint vs never-fired (independent)")

    # Stability. A real signal repeats across seasons and leagues; an artefact
    # concentrates in one slice. This is the check that matters most, because
    # the rule was fixed in advance - nothing here has been fitted to the data.
    for key, title in (("season", "BY SEASON"), ("league", "BY LEAGUE")):
        print("\n%s (signalled vs not, per checkpoint)" % title)
        print("  %-12s %7s %8s %9s %8s" % (key, "signals", "win%", "base%", "lift"))
        for val in sorted({r[key] for r in rows}):
            sub = [r for r in rows if r[key] == val]
            f = [r for r in sub if r["fired"]]
            q = [r for r in sub if not r["fired"]]
            if not f or not q:
                continue
            _, nf, pf, _, _ = rate(f)
            _, _, pq, _, _ = rate(q)
            print("  %-12s %7d %7.1f%% %8.1f%% %+7.1f pp"
                  % (val, nf, 100 * pf, 100 * pq, 100 * (pf - pq)))


if __name__ == "__main__":
    main()
