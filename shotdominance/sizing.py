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


def stake_for(odds, open_total=0.0, conv=None):
    """(stake, assumed_p, kelly_fraction) at the given decimal odds.

    The assumed win probability is the market's implied probability plus an
    edge. The edge has two parts: the odds-shaped curve from the simulator, and
    a tilt for how strong THIS signal is. Passing conv=None reproduces the old
    odds-only behaviour.

    Commission is charged on winnings, so the effective net-odds b is
    (odds-1)*(1-commission). Stake is fractional-Kelly, capped at the per-bet
    limit and by remaining exposure room."""
    edge = _edge_at(odds)
    if conv is not None:
        edge += config.CONV_EDGE_SLOPE * (conv - config.CONV_EDGE_PIVOT)
    p = min(max(1.0 / odds + edge, 0.0), 0.99)
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
    """Full sizing suggestion. The stake is a CONVICTION LADDER, flat in price.

    Kelly is still computed and reported (p, f, kelly) so the alert can show
    what it would have said, and so the two can be compared once the blotter
    has enough settled bets to judge them -- but it no longer sets the stake.
    See config.STAKE_AT_FLOOR for why: Kelly shrinks the bet as the price
    lengthens, and Alf does not want a longer price to mean less money.
    """
    lo, hi = config.CONV_FIRE_MIN, config.CONV_STAKE_TOP
    span = max(hi - lo, 1.0)
    frac = (conv - lo) / span
    frac = max(0.0, min(1.0, frac))
    want = config.STAKE_AT_FLOOR + frac * (config.STAKE_AT_TOP - config.STAKE_AT_FLOOR)
    want = min(want, config.MAX_STAKE_PCT * config.BANKROLL)

    # Kelly, for reporting only
    kelly_stake, p, f = stake_for(price, open_total, conv)

    room = config.MAX_TOTAL_PCT * config.BANKROLL - open_total
    stake = max(0.0, min(want, room))
    bound = "exposure cap" if stake < want - 1e-9 else "conviction ladder"
    return dict(stake=stake, base=config.STAKE_AT_FLOOR,
                mult=(stake / config.STAKE_AT_FLOOR if config.STAKE_AT_FLOOR else 1.0),
                want=want, kelly=kelly_stake, p=p, f=f, bound=bound)
