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


def test_time_factor_is_off_by_default_since_2026_09_13():
    """Time remaining moved OUT of conviction and INTO the required price.

    Leaving both on double-counted time: the boost made the effective evidence
    bar 33% harder at 75' than at 45', which muted exactly the late signals that
    carry the longest prices. See config.MIN_ODDS_GATE.
    """
    assert config.TIME_WEIGHT == 0.0
    for cp in (45, 50, 55, 60, 65, 70, 75):
        assert rules.time_factor(cp) == 1.0     # conviction is pure evidence now


def test_time_factor_still_works_if_deliberately_re_enabled():
    old = config.TIME_WEIGHT
    config.TIME_WEIGHT = 0.5
    try:
        assert rules.time_factor(45) > rules.time_factor(60) > rules.time_factor(75)
        assert abs(rules.time_factor(75) - 1.0) < 1e-9
    finally:
        config.TIME_WEIGHT = old


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
    # a real window is required: an approx reading is capped below the firing
    # floor (2026-09-20), so it would no longer equal the raw blend
    hist = {"t": [rules.Snapshot(25, {"xg": 0.2, "shots": 3, "sot": 1, "box": 1},
                                 {"xg": 0.1, "shots": 1, "sot": 0, "box": 0}, 0)]}
    ev = rules.evaluate(hist, "t", 50, fav, opp, fav_goals=0)
    assert not ev.approx
    base = 0.40 * ev.s_vol + 0.60 * ev.s_mom   # dominance dropped 2026-09-20
    # time factor is off by default, so conviction IS the evidence blend
    assert ev.time_mult == 1.0
    assert abs(ev.conv - min(100.0, base)) < 0.2


def test_due_checkpoint_only_latest_fires():
    done = set()
    # at 63' the reached checkpoints are 45/50/55/60; only 60 is returned and
    # the earlier ones are marked judged so they can never back-fire.
    assert rules.due_checkpoint(done, 63) == 60
    assert done == {45, 50, 55}
    # once 60 is recorded as judged, the same minute yields nothing
    done.add(60)
    assert rules.due_checkpoint(done, 63) is None


# --- minimum price for an edge ---------------------------------------------
def test_win_probability_falls_with_the_clock():
    early = rules.win_probability("level", 45, 60)
    late = rules.win_probability("level", 75, 60)
    assert early > late
    assert 0.55 < early < 0.62          # measured 59.1% at 45'
    assert 0.30 < late < 0.36           # measured 32.8% at 75'


def test_double_chance_decays_more_slowly_than_a_win_bet():
    lvl = rules.win_probability("level", 45, 60) - rules.win_probability("level", 75, 60)
    beh = rules.win_probability("behind", 45, 60) - rules.win_probability("behind", 75, 60)
    assert beh < lvl                     # a draw still settles the DC


def test_strong_evidence_raises_the_probability_as_one_step():
    # measured: <50/50-60/60-70 all ~48%, 70+ jumps to 57.2%
    assert rules.win_probability("level", 60, 55) == rules.win_probability("level", 60, 65)
    assert rules.win_probability("level", 60, 75) > rules.win_probability("level", 60, 65)


def test_min_price_rises_with_time_and_falls_with_evidence():
    assert rules.min_price("level", 75, 60) > rules.min_price("level", 45, 60)
    assert rules.min_price("level", 60, 75) < rules.min_price("level", 60, 60)


def test_min_price_covers_commission_and_margin():
    p = rules.win_probability("level", 60, 60)
    breakeven = 1.0 + (1.0 - p) / (p * (1.0 - config.COMMISSION))
    assert abs(rules.min_price("level", 60, 60)
               - breakeven * (1.0 + config.EDGE_MARGIN)) < 1e-9
    assert breakeven > 1.0 / p           # commission makes it dearer than fair


def test_time_factor_is_off_so_conviction_is_comparable_across_minutes():
    # the whole point of moving time into the price: a score at 21' and a score
    # at 65' now mean the same thing
    assert rules.time_factor(45) == 1.0
    assert rules.time_factor(75) == 1.0


def test_required_price_is_floored_at_the_minimum_backable_odds():
    # early, where break-even is short, the FLOOR binds
    assert rules.min_price("level", 45, 75) == config.MIN_BACKABLE_ODDS
    # late, where break-even is long, BREAK-EVEN binds
    assert rules.min_price("level", 75, 60) > config.MIN_BACKABLE_ODDS


def test_no_percentage_margin_is_applied():
    p = rules.win_probability("level", 75, 60)
    breakeven = 1.0 + (1.0 - p) / (p * (1.0 - config.COMMISSION))
    assert abs(rules.min_price("level", 75, 60) - breakeven) < 1e-9


def test_the_evidence_bonus_survives_past_seventy_minutes():
    # REGRESSION. The 2026-09-13 fit set the 70'+ bonus to zero on a single cell
    # of n=30, so a side dominating 19-11 at 70' was charged the same price as
    # one merely passing the rule. Measured across 45-85 the bonus is +10.9pp and
    # flat in time (+10.7 to 65', +11.4 from 70'). Galatasaray 0-0 Kocaelispor
    # was charged 2.66 at cp70 when the bar should have been the floor.
    for minute in (45, 60, 70, 75, 80):
        strong = rules.win_probability("level", minute, 75)
        weak = rules.win_probability("level", minute, 65)
        assert strong - weak > 0.05, "bonus vanished at %d'" % minute


def test_a_heavy_pre_match_favourite_needs_a_shorter_price():
    # pre-match price is worth MORE than the evidence: +13.2pp for pm<1.35
    # against -7.0pp for pm>2.10, measured on 1,879 rule_ok rows
    heavy = rules.win_probability("level", 65, 75, pm=1.20)
    marginal = rules.win_probability("level", 65, 75, pm=2.60)
    assert heavy > marginal
    assert rules.min_price("level", 65, 75, pm=1.20) < \
        rules.min_price("level", 65, 75, pm=2.60)


def test_the_price_term_is_clamped_outside_the_measured_range():
    # a log-linear fit extrapolated to -16.7pp at 3.00 where the measured bucket
    # is -7.0pp, so the term is clamped at both ends rather than extended
    assert rules._pm_adjustment(1.05) == rules._pm_adjustment(1.20)
    assert rules._pm_adjustment(3.00) == rules._pm_adjustment(8.00)
    assert rules._pm_adjustment(config.WINP_PM_POINTS[0]) == config.WINP_PM_ADJ[0]
    assert rules._pm_adjustment(config.WINP_PM_POINTS[-1]) == config.WINP_PM_ADJ[-1]


def test_the_price_term_is_monotone_in_the_pre_match_price():
    adjs = [rules._pm_adjustment(p) for p in (1.10, 1.30, 1.50, 1.80, 2.20, 3.00)]
    assert adjs == sorted(adjs, reverse=True)


def test_a_missing_pre_match_price_reproduces_the_price_blind_model():
    # callers outside the monitor (board.py, the backtest) may have no pm; they
    # should get the old behaviour rather than a guess
    assert rules._pm_adjustment(None) == 0.0
    assert rules.win_probability("level", 65, 75, pm=None) == \
        rules.win_probability("level", 65, 75)


def test_the_probability_is_capped_where_calibration_stops_holding():
    # above 75% the model over-predicts by ~10pp (n=34, actual 70.6%), because
    # the evidence and pre-match-price terms partly double-count when both are
    # strong. Capping there keeps the required price from being shortened on an
    # estimate the data does not support.
    hot = rules.win_probability("level", 45, 95, pm=1.10)
    assert hot == config.WINP_MAX
    assert rules.win_probability("behind", 45, 95, pm=1.10) == config.WINP_MAX


def test_the_rule_demands_the_same_share_of_whatever_metrics_exist():
    # Measured 2026-09-20 on 34,734 backtest rows: n=3 at (2,2) reproduces the
    # four-metric calibration to within 0.1pp, but n=2 at (2,2) demanded EVERY
    # metric on BOTH axes and passed a third as often. Tabulated so the
    # difference between "2 of 4" and "2 of 2" cannot be hidden in one constant.
    assert rules.rule_thresholds(4) == (config.NEED, config.STRONG_NEED)
    assert rules.rule_thresholds(3) == (config.NEED, config.NEED)
    assert rules.rule_thresholds(2) == (config.NEED_AT_TWO, config.NEED)


def test_a_two_metric_fixture_is_no_longer_asked_for_a_perfect_score():
    need, strong = rules.rule_thresholds(2)
    assert need < 2, "n=2 previously required both metrics on both axes"
    assert strong == 2, "one axis must still clear everything available"


def test_a_fixture_with_one_metric_or_none_can_never_pass():
    for n in (0, 1):
        need, strong = rules.rule_thresholds(n)
        assert strong > n, "n=%d must be unreachable - too little to judge" % n


def test_a_fabricated_momentum_window_cannot_produce_a_confident_score():
    """2026-09-20: Frosinone 2-0 Como scored conviction 80 on vol 0/4 mom 0/4
    because with approx set, s_mom is whole-match totals wearing a momentum
    label - and momentum is 60% of the blend. It cannot cross the firing floor
    or earn the strong-evidence bonus, both of which it did."""
    fav = {"xg": 2.4, "shots": 24, "sot": 9, "box": 15}
    opp = {"xg": 0.1, "shots": 1, "sot": 0, "box": 1}
    ev = rules.evaluate({}, "t", 60, fav, opp, fav_goals=0)   # no history -> approx
    assert ev.approx, "this fixture must have no momentum window"
    assert ev.conv < config.CONV_FIRE_MIN, (
        "approx conviction %.1f reached the firing floor" % ev.conv)
    assert ev.conv < config.WINP_STRONG_FROM, "approx must not earn the bonus"


def test_the_approx_cap_does_not_touch_a_real_window():
    # a genuine reading must be free to score as high as the evidence warrants
    fav = {"xg": 2.4, "shots": 24, "sot": 9, "box": 15}
    opp = {"xg": 0.1, "shots": 1, "sot": 0, "box": 1}
    # the window band is [minute-WINDOW, minute-MIN_WINDOW] = [30, 40] at 60'
    hist = {"t": [rules.Snapshot(32, {"xg": 0.3, "shots": 4, "sot": 1, "box": 2},
                                 {"xg": 0.05, "shots": 1, "sot": 0, "box": 0}, 0)]}
    ev = rules.evaluate(hist, "t", 60, fav, opp, fav_goals=0)
    assert not ev.approx
    assert ev.conv > config.CONV_FIRE_MIN, "a real window must not be capped"
