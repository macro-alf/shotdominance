"""Phase 1b: enumerate candidate rules and score them on stratified lift.

    python -m backtest.sweep --features backtest_features_explore.csv

Every candidate is scored on lift ABOVE the base rate of its own (price,
minute, state) strata, not on raw win rate - see explore.stratified. Raw win
rate is also printed, because that is what was asked for, but it is the weaker
number: filtering to short-priced favourites raises it while adding nothing.

The candidate count is printed at the end. With N candidates the best one beats
the null by roughly 0.5*sqrt(log N) standard errors for free, so the count is
part of the result, not bookkeeping.
"""
import argparse

from . import explore

KEYS = ("xg", "shots", "sot", "box")


def _dom(r, k, limit):
    v = r.get("d_" + k)
    return v is not None and v <= limit


def _mdom(r, k, limit, tag="30"):
    v = r.get("md%s_%s" % (tag, k))
    return v is not None and v <= limit


def build_candidates():
    """Every candidate, declared up front. Refinements of the current signal
    (they subset the 994 fired) unless marked ALT, which re-fires from scratch
    over all eligible checkpoints."""
    c = []

    # --- family A: refine the current signal ---------------------------------
    c.append(("baseline: current fired", lambda r: bool(r["fired"])))
    for k in KEYS:
        for lim in (0.20, 0.35, 0.50):
            c.append(("fired + %s dominance <= %.2f" % (k, lim),
                      (lambda k, lim: lambda r: r["fired"] and _dom(r, k, lim))(k, lim)))
    for lim in (0.35, 0.50):
        c.append(("fired + xg AND shots dom <= %.2f" % lim,
                  (lambda lim: lambda r: r["fired"] and _dom(r, "xg", lim)
                   and _dom(r, "shots", lim))(lim)))
        c.append(("fired + xg AND box dom <= %.2f" % lim,
                  (lambda lim: lambda r: r["fired"] and _dom(r, "xg", lim)
                   and _dom(r, "box", lim))(lim)))
    for t in (55, 60, 65, 70):
        c.append(("fired + conv >= %d" % t,
                  (lambda t: lambda r: r["fired"] and r["conv"] >= t)(t)))
    for t in (1.2, 1.5, 2.0):
        c.append(("fired + xg volume ratio >= %.1f" % t,
                  (lambda t: lambda r: r["fired"] and (r["r_xg"] or 0) >= t)(t)))
    c.append(("fired + level only", lambda r: r["fired"] and r["state"] == "level"))
    c.append(("fired + behind only", lambda r: r["fired"] and r["state"] == "behind"))
    for lim in (0.35, 0.50):
        c.append(("fired + 15min xg surge dom <= %.2f" % lim,
                  (lambda lim: lambda r: r["fired"] and _mdom(r, "xg", lim, "15"))(lim)))
        c.append(("fired + 15min shots surge dom <= %.2f" % lim,
                  (lambda lim: lambda r: r["fired"]
                   and _mdom(r, "shots", lim, "15"))(lim)))
    c.append(("fired + vol_met >= 3", lambda r: r["fired"] and r["vol_met"] >= 3))
    c.append(("fired + mom_met >= 3", lambda r: r["fired"] and r["mom_met"] >= 3))
    c.append(("fired + vol_met>=3 AND mom_met>=3",
              lambda r: r["fired"] and r["vol_met"] >= 3 and r["mom_met"] >= 3))

    # --- family B: alternative firing rules (ALT) ----------------------------
    # Dominance-first rules that ignore the absolute bars entirely, to test
    # whether the volume thresholds are carrying anything.
    for lim in (0.25, 0.35, 0.50):
        c.append(("ALT xg dom <= %.2f alone" % lim,
                  (lambda lim: lambda r: _dom(r, "xg", lim))(lim)))
        c.append(("ALT xg AND shots AND box dom <= %.2f" % lim,
                  (lambda lim: lambda r: _dom(r, "xg", lim) and _dom(r, "shots", lim)
                   and _dom(r, "box", lim))(lim)))
    for t in (45, 50, 55, 60):
        c.append(("ALT conv >= %d (no rule gate)" % t,
                  (lambda t: lambda r: r["conv"] >= t)(t)))
    for t in (50, 55):
        c.append(("ALT rule_ok AND conv >= %d" % t,
                  (lambda t: lambda r: r["rule_ok"] and r["conv"] >= t)(t)))
    # three of four metrics rather than two
    c.append(("ALT rule_ok AND vol_met >= 3", lambda r: r["rule_ok"] and r["vol_met"] >= 3))
    return c


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--features", required=True)
    ap.add_argument("--min-n", type=int, default=60,
                    help="ignore candidates thinner than this - unusable live")
    a = ap.parse_args(argv)

    rows = explore.load(a.features)
    cands = build_candidates()

    results = []
    for name, pred in cands:
        hit = [r for r in rows if pred(r)]
        act, exp, z = explore.stratified(rows, hit)
        results.append({"name": name, "n": len(hit), "act": act,
                        "exp": exp, "lift": act - exp, "z": z or 0.0})

    print("%-44s %6s %7s %7s %8s %7s" % ("candidate", "n", "win%", "exp%",
                                         "lift", "z"))
    print("-" * 84)
    base = next(r for r in results if r["name"].startswith("baseline"))
    for r in sorted(results, key=lambda r: -r["lift"]):
        if r["n"] < a.min_n and not r["name"].startswith("baseline"):
            continue
        mark = "  <-- baseline" if r is base else ""
        print("%-44s %6d %6.1f%% %6.1f%% %+7.1fpp %+6.2f%s"
              % (r["name"], r["n"], r["act"], r["exp"], r["lift"], r["z"], mark))

    thin = sum(1 for r in results if r["n"] < a.min_n)
    print("\n%d candidates evaluated (%d hidden as thinner than n=%d)."
          % (len(results), thin, a.min_n))
    # expected maximum of N standard normals ~ sqrt(2 ln N): the z a search this
    # wide produces from noise alone.
    import math
    print("Under the null, the best of %d candidates scores z ~ %.2f by chance "
          "alone. Anything below that is not a finding."
          % (len(results), math.sqrt(2 * math.log(max(len(results), 2)))))


if __name__ == "__main__":
    main()
