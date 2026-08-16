"""The rule engine - pure functions, no I/O. This is the part specified by
HANDOVER.md, rebuilt from that spec rather than carried over from the patches.

A metric is "realised" only if it clears its (minute-scaled) bar AND we
dominate it - the opponent's value on the same metric is at most DOM_RATIO of
ours. Signal logic then differs by whether the favourite has scored:

  favourite has NOT scored (0-0, 0-1, ...):
      >=2 of 4 on volume AND >=2 of 4 on momentum.
      An incomplete momentum window blocks the signal.

  favourite HAS scored and is level/behind (1-1, 2-2, 1-2):
      >=2 of 4 on momentum, OR >=2 of 4 on cumulative measured against a
      (fav_goals + 1)x threshold. Deliberately looser than the 0-0 case.
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from . import config


@dataclass
class Snapshot:
    """One recorded observation of a fixture."""
    minute: int
    fav: Dict[str, Optional[float]]
    opp: Dict[str, Optional[float]]
    fav_goals: int


@dataclass
class Evaluation:
    ok: bool
    basis: str
    approx: bool
    conv: float
    vol_met: int
    mom_met: int
    n_present: int          # metrics with data (the denominator; 3 when xG absent)
    vol_det: List[str]
    mom_det: List[str]
    extra: List[str]
    s_vol: float
    s_mom: float
    s_dom: float
    s_time: float           # time-remaining as a 0-100 (100 = whole match left)
    time_mult: float        # the multiplier applied to conviction (1.0 when off)
    vol_th: Dict[str, float]
    mom_th: Dict[str, float]


def thresholds(minute):
    """(volume, momentum) threshold dicts at a given minute. Volume scales
    linearly from the minute-45 baseline; momentum is a constant window bar."""
    scale = minute / 45.0
    vol = {k: config.BASE45[k] * scale for k in config.KEYS}
    mom = {k: config.BASE45[k] * (config.WINDOW / 45.0) for k in config.KEYS}
    return vol, mom


def assess(fav, opp, th, dom_ratio=None):
    """How many metrics clear the bar AND are dominated. Returns
    (met, ratios, doms, detail). ratios[k] = value/threshold; doms[k] =
    opponent/ours (None if unknown - never treated as perfect dominance)."""
    dom_ratio = config.DOM_RATIO if dom_ratio is None else dom_ratio
    met, ratios, doms, detail = 0, {}, {}, []
    for k in config.KEYS:
        v, o, need = fav.get(k), opp.get(k), th[k]
        if v is None or need <= 0:
            ratios[k] = None
            doms[k] = None
            detail.append("%s n/a" % k)
            continue
        ratios[k] = v / need
        dom = (o / v) if (o is not None and v > 0) else None
        doms[k] = dom
        abs_ok = v >= need
        dom_ok = dom is not None and dom <= dom_ratio
        if abs_ok and dom_ok:
            met += 1
        detail.append("%s %s %.2f/%.2f opp %s%s"
                      % (k, "OK" if (abs_ok and dom_ok) else "--", v, need,
                         "n/a" if dom is None else "%.0f%%" % (dom * 100),
                         "" if dom_ok else (" (opp unknown)" if dom is None
                                            else " (not dominant)")))
    return met, ratios, doms, detail


def window_delta(history, fid, minute, fav, opp):
    """Favourite and opponent change over the trailing window. approx=True when
    there is no snapshot that far back, in which case the whole match is used
    and the result is EASIER to pass - never treat an approx pass as evidence."""
    base = None
    for snap in history.get(fid) or []:
        if snap.minute <= minute - config.WINDOW:
            base = snap
    if base is None:
        return dict(fav), dict(opp), True

    def delta(cur, prev):
        return {k: (None if cur.get(k) is None
                    else max(0.0, cur[k] - (prev.get(k) or 0)))
                for k in config.KEYS}

    return delta(fav, base.fav), delta(opp, base.opp), False


def score(ratios):
    """0-100 conviction component from ratio-to-threshold values, each capped
    at CONV_CAP. Everything at threshold -> 50; everything at the cap -> 100."""
    vals = [min(r, config.CONV_CAP) for r in ratios.values() if r is not None]
    if not vals:
        return 0.0
    raw = 0.6 * (sum(vals) / len(vals)) + 0.4 * min(vals)
    return max(0.0, min(100.0, 50.0 * raw))


def dom_score(doms):
    """0-100 from how far below DOM_RATIO the opponent-share sits on average."""
    vals = [d for d in doms.values() if d is not None]
    if not vals:
        return 0.0
    mean = sum(vals) / len(vals)
    return max(0.0, min(100.0, 100.0 * (1.0 - mean / config.DOM_RATIO)))


def time_remaining_frac(minute):
    """Fraction of the (nominal) match still to play, 1.0 at the first checkpoint
    down to 0.0 at MATCH_END."""
    span = max(config.MATCH_END - config.CHECKPOINTS[0], 1.0)
    return max(0.0, min(1.0, (config.MATCH_END - minute) / span))


def time_factor(minute):
    """Conviction multiplier from time remaining: >1 earlier in the match, <1
    later, exactly 1.0 at TIME_PIVOT_MIN. TIME_WEIGHT=0 disables it (1.0).

    Rationale: with more of the match left there is more opportunity to turn shot
    dominance into the goal the bet needs, so the same dominance is worth more
    earlier. This is orthogonal to the minute-scaled volume threshold, which
    already normalises for the *rate* of dominance."""
    w = config.TIME_WEIGHT
    if w <= 0:
        return 1.0
    frac = time_remaining_frac(minute)
    pivot = max(0.0, min(1.0, (config.MATCH_END - config.TIME_PIVOT_MIN)
                         / max(config.MATCH_END - config.CHECKPOINTS[0], 1.0)))
    mult = 1.0 + w * (frac - pivot)
    return max(1.0 - w, min(1.0 + w, mult))


def evaluate(history, fid, minute, fav, opp, fav_goals):
    """The full decision for one checkpoint."""
    vol_th, mom_th = thresholds(minute)
    dfav, dopp, approx = window_delta(history, fid, minute, fav, opp)
    mom_met, _mom_r, _mom_d, mom_det = assess(dfav, dopp, mom_th)
    vol_met, vol_r, vol_d, vol_det = assess(fav, opp, vol_th)
    mom_r = _mom_r

    extra = []
    if fav_goals == 0:
        ok = (vol_met >= config.NEED and mom_met >= config.NEED and not approx)
        basis = "0 goals: volume AND momentum"
    else:
        mult = fav_goals + 1
        hard_th = {k: vol_th[k] * mult for k in config.KEYS}
        hard_met, _hr, _hd, hard_det = assess(fav, opp, hard_th)
        a = mom_met >= config.NEED and not approx
        b = hard_met >= config.NEED
        ok = a or b
        basis = ("scored %d: momentum(%s) OR %dx cumulative(%s)"
                 % (fav_goals, "yes" if a else "no", mult, "yes" if b else "no"))
        extra = ["%dx bar: %s" % (mult, "  ".join(hard_det))]

    base_conv = (0.55 * score(vol_r) + 0.30 * score(mom_r)
                 + 0.15 * dom_score(vol_d))
    tmult = time_factor(minute)
    conv = max(0.0, min(100.0, base_conv * tmult))
    # how many of the four metrics actually have data - when xG is missing this
    # is 3, so the requirement is "NEED of 3" rather than "NEED of 4".
    n_present = sum(1 for k in config.KEYS if fav.get(k) is not None)
    return Evaluation(
        ok=ok, basis=basis, approx=approx, conv=round(conv, 1),
        vol_met=vol_met, mom_met=mom_met, n_present=n_present,
        vol_det=vol_det, mom_det=mom_det,
        extra=extra, s_vol=round(score(vol_r), 1), s_mom=round(score(mom_r), 1),
        s_dom=round(dom_score(vol_d), 1),
        s_time=round(100.0 * time_remaining_frac(minute), 1),
        time_mult=round(tmult, 3), vol_th=vol_th, mom_th=mom_th)


def due_checkpoint(done, minute):
    """The highest checkpoint reached but not yet judged. Lower reached-but-
    skipped checkpoints are marked done so the monitor never back-fires on a
    checkpoint it slept through - only the latest one can trigger.

    `done` is the set of already-judged checkpoints for this fixture; it is
    mutated in place."""
    reached = [cp for cp in config.CHECKPOINTS if minute >= cp]
    if not reached:
        return None
    top = max(reached)
    for cp in reached:
        if cp != top:
            done.add(cp)
    return None if top in done else top
