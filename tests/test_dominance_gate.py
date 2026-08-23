"""No alert may fire while the opponent is out-performing the favourite.

FC Zurich 1-1 Basel (2026-08-22) fired with Basel realising 0 of 4 cumulative
metrics and the opponent ahead on xG (1.12 vs 0.94): the scored branch accepts
momentum on its own, so a recent burst carried it. An alert claims "dominating
but not winning", and that one did not mean it.
"""
from shotdominance import config, rules

# cumulative at 70': the real Zurich numbers. Opponent ahead on xG, level or
# close on everything else - nowhere near DOM_RATIO on any metric.
FAV = {"xg": 0.94, "shots": 12, "sot": 5, "box": 9}
OPP = {"xg": 1.12, "shots": 9, "sot": 3, "box": 8}
# a baseline that gives a genuinely strong last-30-minutes burst
BASE_F = {"xg": 0.40, "shots": 6, "sot": 2, "box": 4}
BASE_O = {"xg": 1.00, "shots": 8, "sot": 3, "box": 8}


def _hist(fav=None, opp=None):
    return {"z": [rules.Snapshot(40, dict(fav or BASE_F), dict(opp or BASE_O), 1)]}


def test_momentum_alone_no_longer_carries_a_non_dominant_favourite():
    ev = rules.evaluate(_hist(), "z", 70, FAV, OPP, fav_goals=1)
    assert ev.mom_met >= config.NEED, "momentum must genuinely pass, or this "\
                                      "test proves nothing about the new gate"
    assert ev.cum_dom == 0 and ev.opp_leads >= 1
    assert ev.ok is False
    assert "BLOCKED" in ev.basis


def test_a_genuinely_dominant_favourite_still_fires():
    """Same momentum, but now clearly on top cumulatively."""
    fav = {"xg": 2.20, "shots": 20, "sot": 8, "box": 14}
    opp = {"xg": 0.30, "shots": 4, "sot": 1, "box": 2}
    ev = rules.evaluate(_hist(), "z", 70, fav, opp, fav_goals=1)
    assert ev.cum_dom >= config.CUM_DOM_MIN and ev.opp_leads == 0
    assert ev.ok is True


def test_opponent_ahead_on_a_single_metric_blocks():
    """Dominant on three metrics but the opponent leads xG -> not clear."""
    fav = {"xg": 0.50, "shots": 20, "sot": 8, "box": 14}
    opp = {"xg": 0.90, "shots": 4, "sot": 1, "box": 2}
    ev = rules.evaluate(_hist(), "z", 70, fav, opp, fav_goals=1)
    assert ev.opp_leads == 1 and ev.ok is False
    assert "opponent leads" in ev.basis


def test_the_gate_is_configurable_off():
    """Kept switchable so the cost can be measured rather than assumed."""
    assert config.CUM_DOM_MIN >= 0 and config.NO_OPP_LEAD in (0, 1)
