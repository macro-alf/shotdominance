"""Replay one match through the live rule engine.

This calls `shotdominance.rules.evaluate` itself rather than reimplementing the
rule - the point of Phase 1 is to test the rule that actually runs, so any
divergence between backtest and production would defeat the exercise.

WHAT PHASE 1 DOES AND DOES NOT GATE ON
  Applied:      competition, pre-match favourite band, favourite not winning,
                the 45'-75' checkpoints, the metric/momentum rule, conviction.
  NOT applied:  the live signal-price band (1.75-4.00) and stake sizing. No
                historical in-play odds exist, which is exactly what Phase 2
                adds from Betfair. So Phase 1 answers "does the signal predict
                the outcome", not "is it profitable".

SETTLEMENT mirrors the live blotter:
  favourite level  -> backed to WIN      -> won if the favourite wins at FT.
  favourite behind -> backed DOUBLE CHANCE -> won if it wins or draws at FT.
"""
from shotdominance import config, rules

from . import reconstruct


def favourite(odds_h, odds_a):
    """Pre-match favourite side and price, or None if outside the band.

    Mirrors the live gate: the shorter price is the favourite, and it must sit
    in MIN_ODDS..MAX_ODDS.
    """
    side, price = ("h", odds_h) if odds_h <= odds_a else ("a", odds_a)
    if not (config.MIN_ODDS <= price <= config.MAX_ODDS):
        return None
    return side, price


def settle(state, fav_side, goals_h, goals_a):
    """Did the bet the monitor would have placed win? None if no bet."""
    fav_g, opp_g = (goals_h, goals_a) if fav_side == "h" else (goals_a, goals_h)
    if state == "level":
        return fav_g > opp_g
    if state == "behind":
        return fav_g >= opp_g
    return None


def replay_match(fx, shots):
    """-> list of one row per checkpoint the fixture was eligible at.

    A row is emitted for every eligible checkpoint whether or not it signalled,
    so the analysis can compare signalled against not-signalled from the SAME
    situational population.
    """
    fav = favourite(fx["odds_h"], fx["odds_a"])
    if fav is None:
        return []
    fav_side, fav_price = fav
    opp_side = "a" if fav_side == "h" else "h"

    series, goals = reconstruct.build(shots)
    fh, fa = reconstruct.final_score(goals)
    if (fh, fa) != (fx["goals_h"], fx["goals_a"]):
        return []                      # reconstruction disagrees - drop, loudly counted

    rows = []
    best = 0.0
    for cp in config.CHECKPOINTS:
        fav_g, opp_g = goals[fav_side][cp], goals[opp_side][cp]
        if fav_g > opp_g:
            continue                   # favourite leading - excluded live too
        state = "level" if fav_g == opp_g else "behind"

        hist = reconstruct.history_to(series, goals, fav_side, cp)
        ev = rules.evaluate({fx["match_id"]: hist}, fx["match_id"], cp,
                            series[fav_side][cp], series[opp_side][cp],
                            fav_g, opp_g)

        fired = bool(ev.ok and ev.conv >= config.CONV_FIRE_MIN and ev.conv > best)
        if fired:
            best = ev.conv
        rows.append({
            "match_id": fx["match_id"], "date": fx["date"],
            "home": fx["home"], "away": fx["away"],
            "fav_side": fav_side, "fav_price": fav_price,
            "minute": cp, "state": state,
            "score": "%d-%d" % (fav_g, opp_g),
            "rule_ok": ev.ok, "conv": ev.conv, "fired": fired,
            "vol_met": ev.vol_met, "mom_met": ev.mom_met, "n": ev.n_present,
            "basis": ev.basis,
            "won": settle(state, fav_side, fh, fa),
            "final": "%d-%d" % (fh, fa),
        })
    return rows
