"""Run the FROZEN candidates once against the holdout, and judge them.

    python -m backtest.features --seasons 2014,2015,2016,2017,2018,2019 \
        --out backtest_features_holdout.csv
    python -m backtest.confirm --features backtest_features_holdout.csv

The verdicts are the ones written down in candidates.py before this was run:

  SURVIVED  beats the baseline's holdout lift AND keeps at least half its own
            in-sample lift.
  DECAYED   still positive, but lost more than half the in-sample lift, or
            failed to beat the baseline. A refinement that cuts breadth without
            beating the thing it refines has done nothing.
  FAILED    no meaningful lift on data it had not seen.

This script is run ONCE. Re-running it with adjusted thresholds would turn the
holdout into a second training set, which is the exact failure this project
already had (an optimisation pass that read +119% in sample and +39.5% out).
"""
import argparse
import math

from . import candidates, explore


def verdict(hold_lift, base_lift, in_lift, z):
    if hold_lift <= 0 or (z is not None and z < 1.0):
        return "FAILED"
    if hold_lift < 0.5 * in_lift:
        return "DECAYED"
    if hold_lift <= base_lift:
        return "DECAYED"
    return "SURVIVED"


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--features", required=True)
    a = ap.parse_args(argv)

    rows = explore.load(a.features)
    seasons = sorted({r["season"] for r in rows})
    print("HOLDOUT: %d checkpoint rows, seasons %s, %d fixtures"
          % (len(rows), ",".join(seasons), len({r["match_id"] for r in rows})))
    print("Search size in sample: %d candidates -> best-of-N noise ~%.1f SE\n"
          % (candidates.N_SEARCHED,
             math.sqrt(2 * math.log(candidates.N_SEARCHED))))

    results = {}
    for name, pred in candidates.FROZEN:
        hit = [r for r in rows if pred(r)]
        act, exp, z = explore.stratified(rows, hit)
        results[name] = (len(hit), act, act - exp, z or 0.0)

    base_name = candidates.FROZEN[0][0]
    base_lift = results[base_name][2]

    print("%-48s %6s %7s %8s %7s %9s %-9s"
          % ("candidate", "n", "win%", "lift", "z", "in-samp", "verdict"))
    print("-" * 100)
    for name, _ in candidates.FROZEN:
        n, act, lift, z = results[name]
        in_n, in_win, in_lift = candidates.IN_SAMPLE[name]
        v = ("baseline" if name == base_name
             else verdict(lift, base_lift, in_lift, z))
        print("%-48s %6d %6.1f%% %+7.1fpp %+6.2f %+8.1fpp %-9s"
              % (name, n, act, lift, z, in_lift, v))

    print("\nBreadth-adjusted (lift x sqrt(n)) - governs how fast a real edge "
          "shows up in a book of bets:")
    for name, _ in candidates.FROZEN:
        n, act, lift, z = results[name]
        print("  %-48s %6.0f" % (name, lift * math.sqrt(n) if n else 0.0))


if __name__ == "__main__":
    main()
