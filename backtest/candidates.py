"""FROZEN candidate list for the Phase 1b holdout. Committed 2026-08-16, BEFORE
the 2014-2019 holdout was computed.

This file exists so the confirmation cannot be rewritten after the fact. The
search that produced these ran over 2020-2023 only; 46 candidates were
evaluated (see sweep.py), so under the null the best of them beats the base
rate by about sqrt(2*ln 46) = 2.8 standard errors for free. Nothing below is a
finding until it survives data that had never been looked at.

IN-SAMPLE RESULTS (2020-2023), recorded here so the holdout comparison is a
prediction rather than a description. "lift" is stratified: win rate minus the
base rate of the same (price bucket, minute, state) cells, which is what
removes the reward for simply picking short prices and early minutes.

    id  rule                                   n     win%    lift
    --  ----                                   ----  -----   -----
    B   baseline (current fired rule)           994  51.1%   +6.6pp
    C1  fired + box dominance <= 0.35           601  54.7%   +9.2pp
    C2  fired + xg volume ratio >= 1.2          729  52.5%   +8.4pp
    C3  fired + C1 and C2                       437  56.5%  +11.3pp
    C4  broad: xg,shots,box dominance <= 0.50  3132  47.1%   +5.7pp

KNOWN WARNING SIGN, recorded before the holdout: C1's in-sample lift is NOT
stable across seasons - +14.6, +14.3, +7.3, +0.7pp for 2020, 2021, 2022, 2023.
A refinement that decays to nothing in the most recent season is the classic
shape of an artefact. C2 is steadier (+9.4, +14.3, +4.6, +4.5). If C1 fails on
the holdout, that is the expected outcome, not a surprise.

PREDICTIONS (what would make each candidate real):
  - C1/C2/C3 must beat B's holdout lift, not merely be positive. A refinement
    that keeps a positive lift while cutting breadth in half has done nothing.
  - C4 trades lift for breadth. Judge it on lift*sqrt(n), which is what governs
    how quickly a real edge becomes measurable in a portfolio of bets.
  - Anything whose holdout lift falls below ~half its in-sample lift should be
    treated as overfit and dropped.
"""


def _dom(r, k, limit):
    v = r.get("d_" + k)
    return v is not None and v <= limit


FROZEN = [
    ("B  baseline (current fired rule)", lambda r: bool(r["fired"])),
    ("C1 fired + box dom <= 0.35",
     lambda r: r["fired"] and _dom(r, "box", 0.35)),
    ("C2 fired + xg vol ratio >= 1.2",
     lambda r: r["fired"] and (r["r_xg"] or 0) >= 1.2),
    ("C3 fired + box dom <= 0.35 AND xg ratio >= 1.2",
     lambda r: r["fired"] and _dom(r, "box", 0.35) and (r["r_xg"] or 0) >= 1.2),
    ("C4 broad: xg,shots,box dom <= 0.50",
     lambda r: _dom(r, "xg", 0.50) and _dom(r, "shots", 0.50)
     and _dom(r, "box", 0.50)),
]

IN_SAMPLE = {
    "B  baseline (current fired rule)": (994, 51.1, 6.6),
    "C1 fired + box dom <= 0.35": (601, 54.7, 9.2),
    "C2 fired + xg vol ratio >= 1.2": (729, 52.5, 8.4),
    "C3 fired + box dom <= 0.35 AND xg ratio >= 1.2": (437, 56.5, 11.3),
    "C4 broad: xg,shots,box dom <= 0.50": (3132, 47.1, 5.7),
}

N_SEARCHED = 46
