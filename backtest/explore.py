"""Phase 1b exploration helpers - queries over the feature matrix.

Every number here is IN-SAMPLE on 2020-2023 and means nothing on its own. A
candidate only counts once it has been confirmed on the untouched 2014-2019
holdout, and only after the size of the search is reported, because the best of
N searched configurations beats the base rate by roughly 0.5*sqrt(log N)
standard errors under the null.

Breadth is printed next to every win rate on purpose. Raising the win rate by
discarding signals is not automatically an improvement: 60% on 20 bets a season
is worse than 52% on 300 if the price is right.
"""
import csv
import math

NUMERIC_PREFIXES = ("v_", "o_", "r_", "d_", "m30_", "md30_", "m15_", "md15_")


def load(path):
    rows = []
    with open(path, encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            for k, v in list(r.items()):
                if k in ("match_id", "season", "league", "date", "state"):
                    continue
                if v == "":
                    r[k] = None
                elif k.startswith(NUMERIC_PREFIXES) or k in (
                        "conv", "s_vol", "s_mom", "s_dom", "time_mult", "fav_price"):
                    r[k] = float(v)
                else:
                    r[k] = int(float(v))
            rows.append(r)
    return rows


def wr(rows):
    n = len(rows)
    if not n:
        return 0, 0.0
    return n, 100.0 * sum(r["won"] for r in rows) / n


def se_diff(rows_a, rows_b):
    """z for the difference in win rate between two disjoint groups."""
    na, pa = len(rows_a), (sum(r["won"] for r in rows_a) / len(rows_a)) if rows_a else 0
    nb, pb = len(rows_b), (sum(r["won"] for r in rows_b) / len(rows_b)) if rows_b else 0
    if not na or not nb:
        return None
    p = (pa * na + pb * nb) / (na + nb)
    s = math.sqrt(p * (1 - p) * (1 / na + 1 / nb))
    return (pa - pb) / s if s else None


def deciles(rows, key, bins=10, only=None):
    """Win rate across the distribution of `key`. Shape beats thresholds: a
    monotone curve is evidence the variable carries information, whereas a
    single lucky cut point is not."""
    sub = [r for r in rows if (only is None or only(r)) and r.get(key) is not None]
    sub.sort(key=lambda r: r[key])
    if not sub:
        return []
    step = max(len(sub) // bins, 1)
    out = []
    for i in range(0, len(sub), step):
        chunk = sub[i:i + step]
        if len(chunk) < step // 2 and out:
            out[-1][3].extend(chunk)
            continue
        n, p = wr(chunk)
        out.append([chunk[0][key], chunk[-1][key], n, chunk])
    return [(lo, hi, len(c), wr(c)[1]) for lo, hi, n, c in out]


def show_deciles(rows, key, only=None, label=None, bins=10):
    print("\n  %-14s %14s %7s %8s" % (label or key, "range", "n", "win%"))
    for lo, hi, n, p in deciles(rows, key, bins=bins, only=only):
        print("  %-14s %6.2f-%-7.2f %7d %7.1f%%" % ("", lo, hi, n, p))


def group(rows, key, only=None):
    sub = [r for r in rows if only is None or only(r)]
    out = {}
    for r in sub:
        out.setdefault(r[key], []).append(r)
    print("\n  %-14s %7s %8s" % (key, "n", "win%"))
    for k in sorted(out):
        n, p = wr(out[k])
        print("  %-14s %7d %7.1f%%" % (k, n, p))


PRICE_BUCKETS = (1.45, 1.60, 1.75, 1.95)


def stratum(r):
    """The situation a bookmaker already knows about: how strong the favourite
    was, how much time is left, and whether it is level or behind."""
    p = r["fav_price"]
    b = sum(1 for edge in PRICE_BUCKETS if p >= edge)
    return (b, r["minute"], r["state"])


def stratified(rows, hit):
    """Actual win rate of `hit` vs what the SAME mix of situations wins on
    average. This is the number that matters.

    Win rate on its own rewards selecting short-priced favourites and early
    checkpoints - both of which win more often precisely because they pay less.
    Standardising against the base rate of the same (price, minute, state)
    strata removes that, leaving only information the situation does not
    already contain. A filter that merely picks cheap situations scores ~0.
    """
    base = {}
    for r in rows:
        s = stratum(r)
        n, k = base.get(s, (0, 0))
        base[s] = (n + 1, k + r["won"])
    if not hit:
        return 0.0, 0.0, None
    expected = 0.0
    for r in hit:
        n, k = base.get(stratum(r), (0, 0))
        expected += (k / n) if n else 0.0
    exp_rate = 100.0 * expected / len(hit)
    act = 100.0 * sum(r["won"] for r in hit) / len(hit)
    # variance of the sum of independent Bernoullis with the stratum means
    var = 0.0
    for r in hit:
        n, k = base.get(stratum(r), (0, 0))
        p = (k / n) if n else 0.0
        var += p * (1 - p)
    z = ((act - exp_rate) / 100.0 * len(hit) / math.sqrt(var)) if var > 0 else None
    return act, exp_rate, z


def candidate(rows, name, pred, universe=None):
    """Evaluate one candidate rule. Returns (name, n, win%, z vs the rest)."""
    uni = [r for r in rows if universe is None or universe(r)]
    hit = [r for r in uni if pred(r)]
    rest = [r for r in uni if not pred(r)]
    n, p = wr(hit)
    z = se_diff(hit, rest)
    return {"name": name, "n": n, "win": p, "z": z}


def table(cands, baseline=None):
    print("\n  %-46s %6s %8s %7s" % ("candidate", "n", "win%", "z"))
    if baseline:
        n, p = wr(baseline)
        print("  %-46s %6d %7.1f%% %7s" % ("[baseline: current fired signal]", n, p, "-"))
    for c in sorted(cands, key=lambda c: -c["win"]):
        print("  %-46s %6d %7.1f%% %+7.2f"
              % (c["name"], c["n"], c["win"], c["z"] if c["z"] is not None else 0.0))
