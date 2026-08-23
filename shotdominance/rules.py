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

BOTH branches additionally require a REAL trailing window. If no usable
baseline exists WINDOW minutes back, the evaluation is approx - the whole match
stands in for the window - and nothing fires, because an alert would then show
cumulative totals under a "Last 30 min" heading and invite a bet on evidence
that was never measured.
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
    win_min: int            # minutes the momentum window ACTUALLY covered (0 = none)
    cum_dom: int            # cumulative metrics where we dominate (opp <= DOM_RATIO)
    opp_leads: int          # metrics where the OPPONENT is ahead of us
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


def thresholds(minute, window=None):
    """(volume, momentum) threshold dicts at a given minute.

    Volume scales linearly from the minute-45 baseline. The momentum bar scales
    with the window ACTUALLY measured, not the nominal one: a 20-minute window
    must clear a 20-minute bar, or a short window would be judged against a bar
    built for half as much football again and never pass."""
    scale = minute / 45.0
    vol = {k: config.BASE45[k] * scale for k in config.KEYS}
    w = config.WINDOW if window is None else window
    mom = {k: config.BASE45[k] * (w / 45.0) for k in config.KEYS}
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


def n_dom_present(doms):
    """How many metrics have a usable opponent share at all."""
    return sum(1 for v in doms.values() if v is not None)


def _has_data(stat):
    return any(stat.get(k) is not None for k in config.KEYS)


def window_delta(history, fid, minute, fav, opp):
    """Change over the trailing window. -> (dfav, dopp, approx, win_min).

    Uses the LONGEST window the feed can actually support, capped at WINDOW and
    floored at MIN_WINDOW, and reports how many minutes that was so the bar can
    be scaled to it and the alert can say so.

    Why not simply demand WINDOW: Tier 2 feeds publish statistics late. Dundalk
    v Galway (2026-08-21) reported nothing until minute 26, so a 50' checkpoint
    had no minute-20 baseline and was blocked outright even though 3 of 4
    metrics were realised. Measuring the 24 minutes that DID exist, against a
    24-minute bar, is real evidence; pretending 24 minutes of play is 30 is not,
    and neither is silently substituting the whole match.

    A MISSING BASELINE IS UNKNOWN, NOT ZERO. This once read `prev.get(k) or 0`,
    so a None baseline became 0 and the "delta" equalled the full cumulative
    total - momentum collapsed into a copy of volume and the 0-goals branch
    fired on one piece of evidence while reporting two (Sion v Ajax, conviction
    85, 2026-08-20).
    """
    snaps = history.get(fid) or []
    # The window is ALWAYS the last WINDOW minutes from now. A baseline older
    # than that would measure more than 30 minutes of football and call it
    # momentum, so the band is closed at both ends: never longer than WINDOW,
    # never shorter than MIN_WINDOW.
    lo, hi = minute - config.WINDOW, minute - config.MIN_WINDOW
    in_band = [s for s in snaps
               if lo <= s.minute <= hi and _has_data(s.fav)]
    if not in_band:
        return dict(fav), dict(opp), True, 0
    # Earliest inside the band = the longest window available, so a full 30 is
    # used whenever the feed supports it and a shorter one only when it does not.
    base = in_band[0]

    def delta(cur, prev):
        return {k: (None if cur.get(k) is None or prev.get(k) is None
                    else max(0.0, cur[k] - prev[k]))
                for k in config.KEYS}

    dfav, dopp = delta(fav, base.fav), delta(opp, base.opp)
    if all(v is None for v in dfav.values()):
        return dict(fav), dict(opp), True, 0
    return dfav, dopp, False, minute - base.minute


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
    dfav, dopp, approx, win_min = window_delta(history, fid, minute, fav, opp)
    vol_th, mom_th = thresholds(minute, win_min or config.WINDOW)
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

    # CLEAR DOMINANCE. An alert claims the favourite is dominating but not
    # winning, so it must not fire while the opponent is out-performing it on
    # the run of play. FC Zurich 1-1 Basel (2026-08-23) realised 0 of 4
    # cumulative metrics with the opponent ahead on xG and still fired, because
    # the scored branch accepts momentum on its own.
    cum_dom = sum(1 for k in config.KEYS
                  if vol_d.get(k) is not None and vol_d[k] <= config.DOM_RATIO)
    opp_leads = sum(1 for k in config.KEYS
                    if vol_d.get(k) is not None and vol_d[k] > 1.0)
    if ok and cum_dom < config.CUM_DOM_MIN:
        ok = False
        basis += " [BLOCKED: dominant on %d/%d cumulative, need %d]" % (
            cum_dom, n_dom_present(vol_d), config.CUM_DOM_MIN)
    elif ok and config.NO_OPP_LEAD and opp_leads:
        ok = False
        basis += " [BLOCKED: opponent leads on %d metric(s)]" % opp_leads

    # NO ALERT MAY REST ON - OR DISPLAY - A MOMENTUM WINDOW WE DO NOT HAVE.
    # When approx is set, window_delta handed back the whole match in place of
    # the trailing window, so the "Last N min" block in the Telegram alert would
    # be cumulative totals wearing a momentum label. The 0-goals branch already
    # refused those, but the scored branch's cumulative test (b) did not, so a
    # favourite that had already scored could alert off a fabricated window.
    # Alerts are meant to be actionable without re-checking the feed by hand.
    if approx:
        ok = False
        basis += " [BLOCKED: no momentum window >= %dmin]" % config.MIN_WINDOW

    base_conv = (0.55 * score(vol_r) + 0.30 * score(mom_r)
                 + 0.15 * dom_score(vol_d))
    tmult = time_factor(minute)
    conv = max(0.0, min(100.0, base_conv * tmult))
    # how many of the four metrics actually have data - when xG is missing this
    # is 3, so the requirement is "NEED of 3" rather than "NEED of 4".
    n_present = sum(1 for k in config.KEYS if fav.get(k) is not None)
    return Evaluation(
        ok=ok, basis=basis, approx=approx, conv=round(conv, 1),
        vol_met=vol_met, mom_met=mom_met, n_present=n_present, win_min=win_min,
        cum_dom=cum_dom, opp_leads=opp_leads,
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
