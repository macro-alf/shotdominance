"""Rule-engine tests. These pin the HANDOVER.md spec: the dominance test, the
conviction scale (threshold -> 50, double -> 100), the 0-0 AND branch, the
scored EITHER/OR branch, and checkpoint bookkeeping.
"""
from shotdominance import config, rules
from shotdominance.rules import Snapshot


def th(**kw):
    """A threshold dict; unspecified metrics default to 1.0."""
    return {k: kw.get(k, 1.0) for k in config.KEYS}


# --- dominance --------------------------------------------------------------
def test_metric_needs_both_bar_and_dominance():
    fav = {"xg": 2.0, "shots": 2, "sot": 2, "box": 2}
    # opponent at exactly 50% -> dominated (<=); above -> not dominated
    opp_ok = {"xg": 1.0, "shots": 1, "sot": 1, "box": 1}
    opp_bad = {"xg": 1.5, "shots": 2, "sot": 2, "box": 2}
    met_ok, _, _, _ = rules.assess(fav, opp_ok, th())
    met_bad, _, _, _ = rules.assess(fav, opp_bad, th())
    assert met_ok == 4
    assert met_bad == 0


def test_missing_opponent_is_not_perfect_dominance():
    fav = {"xg": 2.0, "shots": 2, "sot": 2, "box": 2}
    opp = {"xg": None, "shots": None, "sot": None, "box": None}
    met, _, doms, _ = rules.assess(fav, opp, th())
    assert met == 0
    assert all(d is None for d in doms.values())


def test_missing_value_never_passes():
    fav = {"xg": None, "shots": None, "sot": None, "box": None}
    opp = {"xg": 0.0, "shots": 0, "sot": 0, "box": 0}
    met, ratios, _, _ = rules.assess(fav, opp, th())
    assert met == 0
    assert all(r is None for r in ratios.values())


# --- conviction -------------------------------------------------------------
def test_score_threshold_is_fifty():
    ratios = {k: 1.0 for k in config.KEYS}
    assert rules.score(ratios) == 50.0


def test_score_double_is_hundred():
    ratios = {k: 2.0 for k in config.KEYS}
    assert rules.score(ratios) == 100.0


def test_score_caps_at_double():
    ratios = {k: 5.0 for k in config.KEYS}   # far above the 2x cap
    assert rules.score(ratios) == 100.0


def test_dom_score_extremes():
    at_limit = {k: config.DOM_RATIO for k in config.KEYS}
    total = {k: 0.0 for k in config.KEYS}
    assert rules.dom_score(at_limit) == 0.0
    assert rules.dom_score(total) == 100.0


# --- thresholds -------------------------------------------------------------
def test_volume_scales_momentum_constant():
    """SPEC CHANGE 2026-08-23: the volume bar still anchors at BASE45 on the 45'
    checkpoint, but grows at VOL_SCALE_RATE of its old pace afterwards."""
    vol45, mom45 = rules.thresholds(45)
    vol75, mom75 = rules.thresholds(75)
    assert vol45["shots"] == 10.0
    expected75 = 10.0 * (1.0 + config.VOL_SCALE_RATE * (75 - 45) / 45.0)
    assert abs(vol75["shots"] - expected75) < 1e-9
    assert vol75["shots"] < 10.0 * 75 / 45          # lower than the old bar
    # momentum is a constant window bar regardless of minute
    assert mom45 == mom75
    assert abs(mom45["shots"] - 10.0 * config.WINDOW / 45) < 1e-9


# --- signal branches --------------------------------------------------------
def _dominant_history(fid, minute):
    """History with a baseline snapshot 30+ minutes back so momentum is not
    approx, and near-zero opponent so dominance always holds."""
    early = Snapshot(minute - config.WINDOW,
                     {"xg": 0.0, "shots": 0, "sot": 0, "box": 0},
                     {"xg": 0.0, "shots": 0, "sot": 0, "box": 0}, 0)
    return {fid: [early]}


def test_zero_zero_requires_volume_and_momentum():
    fid, minute = "1", 75
    hist = _dominant_history(fid, minute)
    fav = {"xg": 3.0, "shots": 30, "sot": 9, "box": 15}   # way over the bar
    opp = {"xg": 0.1, "shots": 1, "sot": 0, "box": 0}
    ev = rules.evaluate(hist, fid, minute, fav, opp, fav_goals=0)
    assert ev.ok
    assert ev.vol_met >= config.NEED and ev.mom_met >= config.NEED


def test_zero_zero_blocked_by_incomplete_window():
    fid, minute = "2", 75
    fav = {"xg": 3.0, "shots": 30, "sot": 9, "box": 15}
    opp = {"xg": 0.1, "shots": 1, "sot": 0, "box": 0}
    ev = rules.evaluate({}, fid, minute, fav, opp, fav_goals=0)  # no history
    assert ev.approx
    assert not ev.ok            # incomplete momentum window blocks the 0-0 case


def test_scored_case_needs_a_real_window_too():
    """SPEC CHANGE 2026-08-21: no alert may rest on a momentum window that does
    not exist. This case used to fire - a goal on the board plus a big
    cumulative total carried it through even with no window at all - but the
    Telegram alert then printed whole-match totals under a "Last 30 min"
    heading, inviting a bet on evidence that was never measured."""
    fid, minute = "3", 75
    fav = {"xg": 6.0, "shots": 60, "sot": 18, "box": 30}   # clears even 2x
    opp = {"xg": 0.1, "shots": 1, "sot": 0, "box": 0}
    ev = rules.evaluate({}, fid, minute, fav, opp, fav_goals=1)
    assert ev.approx            # no history -> no window
    assert not ev.ok
    assert "BLOCKED" in ev.basis


def test_scored_case_needs_evidence_on_BOTH_sides():
    """SPEC CHANGE 2026-08-24: the scored branch used to be either/or, so a big
    cumulative total fired with almost no momentum - and symmetrically Hellas
    Verona fired on momentum alone with cumulative at 1 of 4. Both are thin
    evidence for a real bet. One side must now be STRONG and the other at least
    adequate, so a lopsided case no longer fires."""
    fid, minute = "3", 75
    base = rules.Snapshot(45, {"xg": 5.5, "shots": 58, "sot": 17, "box": 29},
                          {"xg": 0.05, "shots": 0, "sot": 0, "box": 0}, 1)
    fav = {"xg": 6.0, "shots": 60, "sot": 18, "box": 30}
    opp = {"xg": 0.1, "shots": 1, "sot": 0, "box": 0}
    ev = rules.evaluate({fid: [base]}, fid, minute, fav, opp, fav_goals=1)
    assert not ev.approx
    assert ev.mom_met < 2       # only a trickle in the last 30 minutes
    assert not ev.ok            # ...and cumulative alone no longer carries it
    assert "BLOCKED" in ev.basis


# --- checkpoints ------------------------------------------------------------
def test_evaluate_reports_present_metric_count():
    # xG absent -> denominator 3 (the rule becomes "NEED of 3")
    fav_no_xg = {"xg": None, "shots": 30, "sot": 9, "box": 15}
    opp = {"xg": None, "shots": 1, "sot": 0, "box": 0}
    ev = rules.evaluate({}, "9", 75, fav_no_xg, opp, fav_goals=0)
    assert ev.n_present == 3
    # all four present -> denominator 4
    fav_all = {"xg": 3.0, "shots": 30, "sot": 9, "box": 15}
    ev2 = rules.evaluate({}, "9", 75, fav_all, opp, fav_goals=0)
    assert ev2.n_present == 4


def test_time_factor_boost_only_default():
    # shipped default: enabled (0.5) with pivot at the last checkpoint (75) ->
    # boost-only: >=1 everywhere, strongest at 45', exactly 1.0 at 75'.
    assert config.TIME_WEIGHT == 0.5 and config.TIME_PIVOT_MIN == 75.0
    assert abs(rules.time_factor(75) - 1.0) < 1e-9
    assert rules.time_factor(45) > rules.time_factor(60) > rules.time_factor(75)
    for cp in (45, 50, 55, 60, 65, 70, 75):
        assert rules.time_factor(cp) >= 1.0 - 1e-9      # never below 1 (boost-only)
    assert abs(rules.time_factor(45) - (1.0 + config.TIME_WEIGHT * (1.0 - 1.0/3.0))) < 1e-6


def test_time_factor_disabled_when_weight_zero():
    old = config.TIME_WEIGHT
    try:
        config.TIME_WEIGHT = 0.0
        assert rules.time_factor(45) == 1.0 and rules.time_factor(75) == 1.0
    finally:
        config.TIME_WEIGHT = old


def test_time_factor_symmetric_when_pivot_60():
    old_w, old_p = config.TIME_WEIGHT, config.TIME_PIVOT_MIN
    try:
        config.TIME_WEIGHT, config.TIME_PIVOT_MIN = 0.5, 60.0
        assert abs(rules.time_factor(60) - 1.0) < 1e-9
        assert rules.time_factor(45) > 1.0 and rules.time_factor(75) < 1.0
    finally:
        config.TIME_WEIGHT, config.TIME_PIVOT_MIN = old_w, old_p


def test_conviction_scales_by_time_factor():
    fav = {"xg": 1.6, "shots": 18, "sot": 6, "box": 9}
    opp = {"xg": 0.2, "shots": 2, "sot": 0, "box": 1}
    ev = rules.evaluate({}, "t", 50, fav, opp, fav_goals=0)   # default (enabled)
    base = 0.55 * ev.s_vol + 0.30 * ev.s_mom + 0.15 * ev.s_dom
    assert ev.time_mult > 1.0                                # 50' is before 75' pivot
    assert abs(ev.conv - min(100.0, base * ev.time_mult)) < 0.2


def test_due_checkpoint_only_latest_fires():
    done = set()
    # at 63' the reached checkpoints are 45/50/55/60; only 60 is returned and
    # the earlier ones are marked judged so they can never back-fire.
    assert rules.due_checkpoint(done, 63) == 60
    assert done == {45, 50, 55}
    # once 60 is recorded as judged, the same minute yields nothing
    done.add(60)
    assert rules.due_checkpoint(done, 63) is None
