"""Stake sizing. Two layers:

  stake_for(odds)  - fractional-Kelly stake from the model edge curve. This is
                     the CEILING, not the target.
  size(price, conv) - the actual suggestion: a target-win base scaled by a
                     conviction multiplier, then clamped by the Kelly ceiling
                     and the open-exposure cap.

The edge behind Kelly is model output, not a measured quantity.
"""
from . import config


def _edge_at(odds):
    pts = sorted(config.EDGE)
    if odds <= pts[0][0]:
        return pts[0][1]
    if odds >= pts[-1][0]:
        return pts[-1][1]
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        if x0 <= odds <= x1:
            return y0 + (y1 - y0) * (odds - x0) / (x1 - x0)
    return pts[-1][1]


def stake_for(odds, open_total=0.0):
    """(stake, assumed_p, kelly_fraction) at the given decimal odds.

    Commission is charged on winnings, so the effective net-odds b is
    (odds-1)*(1-commission). Stake is fractional-Kelly, capped at the per-bet
    limit and by remaining exposure room."""
    edge = _edge_at(odds)
    p = min(1.0 / odds + edge, 0.99)
    b = (odds - 1.0) * (1.0 - config.COMMISSION)
    if b <= 0:
        return 0.0, p, 0.0
    f = max((p * (1 + b) - 1) / b, 0.0) * config.KELLY_FRAC
    stake = min(f * config.BANKROLL, config.MAX_STAKE_PCT * config.BANKROLL)
    room = config.MAX_TOTAL_PCT * config.BANKROLL - open_total
    return max(min(stake, room), 0.0), p, f


def conviction_multiplier(conv):
    span = max(config.CONV_TOP - config.CONV_MID, 1)
    raw = 1.0 + (config.MULT_MAX - 1.0) * (conv - config.CONV_MID) / span
    return max(config.MULT_MIN, min(config.MULT_MAX, raw))


def size(price, conv, open_total=0.0):
    """Full sizing suggestion. Returns a dict with the stake and the reasoning
    (base, multiplier, Kelly ceiling, and which constraint bound it)."""
    base = config.TARGET_WIN / (price - 1.0)
    mult = conviction_multiplier(conv)
    want = base * mult
    kelly_stake, p, f = stake_for(price, open_total)
    stake = min(want, kelly_stake)
    room = config.MAX_TOTAL_PCT * config.BANKROLL - open_total
    stake = max(0.0, min(stake, room))
    bound = ("Kelly" if kelly_stake < want
             else ("exposure cap" if stake < want else "target-win"))
    return dict(stake=stake, base=base, mult=mult, want=want,
                kelly=kelly_stake, p=p, f=f, bound=bound)
