"""The absolute volume bar: half-speed clock scaling, and what the NEXT goal costs.

Two changes on 2026-08-23:
  - the bar grows at VOL_SCALE_RATE of its old pace after the 45' anchor, because
    Manchester City 0-1 Bournemouth was dominant on 3 of 4 metrics (xG 1.55 v
    0.55, shots 10 v 4) yet cleared the absolute bar on only one - 10 shots is a
    lot of football against a bar of 17.3;
  - a favourite that has ALREADY scored is judged against a doubled bar, since
    at 1-1 the question is whether it has done enough to score TWICE.
"""
from shotdominance import config, rules


def test_bar_is_unchanged_at_the_45_anchor():
    """Halving the growth must not move the anchor - 45' is the calibration
    point the whole BASE45 table was set from."""
    vol, _ = rules.thresholds(45, fav_goals=0)
    for k in config.KEYS:
        assert abs(vol[k] - config.BASE45[k]) < 1e-9


def test_bar_grows_at_half_the_old_pace_after_45():
    vol, _ = rules.thresholds(78, fav_goals=0)
    old = config.BASE45["shots"] * 78 / 45.0          # the previous formula
    growth_old = old - config.BASE45["shots"]
    growth_new = vol["shots"] - config.BASE45["shots"]
    assert abs(growth_new - config.VOL_SCALE_RATE * growth_old) < 1e-9
    assert vol["shots"] < old, "the point of the change is a lower bar"


def test_a_scored_favourite_is_judged_on_the_SECOND_goal():
    at0, _ = rules.thresholds(60, fav_goals=0)
    at1, _ = rules.thresholds(60, fav_goals=1)
    at2, _ = rules.thresholds(60, fav_goals=2)
    for k in config.KEYS:
        assert abs(at1[k] - 2 * at0[k]) < 1e-9
        assert abs(at2[k] - 3 * at0[k]) < 1e-9


def test_momentum_bar_is_NOT_multiplied_by_goals():
    """Momentum asks whether the side is on top right now; that does not change
    because it scored half an hour ago."""
    _v0, m0 = rules.thresholds(60, fav_goals=0)
    _v2, m2 = rules.thresholds(60, fav_goals=2)
    assert m0 == m2


def test_momentum_bar_still_tracks_the_measured_window():
    _v, m20 = rules.thresholds(60, window=20)
    _v, m30 = rules.thresholds(60, window=30)
    assert abs(m20["shots"] / m30["shots"] - 20.0 / 30.0) < 1e-9


def test_manchester_city_would_now_clear_more_metrics():
    """City at 78': xg 1.55, shots 10, sot 3, box 8 against Bournemouth's
    0.55/4/3/3. Level on goals, so no doubling. Under the old bar it realised
    one metric; the halved bar should reach the 2-of-4 the rule needs."""
    fav = {"xg": 1.55, "shots": 10, "sot": 3, "box": 8}
    opp = {"xg": 0.55, "shots": 4, "sot": 3, "box": 3}
    vol, _ = rules.thresholds(78, fav_goals=0)
    met = sum(1 for k in config.KEYS
              if fav[k] >= vol[k] and opp[k] <= config.DOM_RATIO * fav[k])
    assert met >= config.NEED, "still %d of 4 at the halved bar" % met


def test_the_multiplier_generalises_to_any_number_of_goals():
    """2-2 needs a third, 3-3 needs a fourth. The bar is always what the NEXT
    goal costs, on EVERY metric - not just shots."""
    base, _ = rules.thresholds(60, fav_goals=0)
    for goals in (0, 1, 2, 3, 4):
        vol, _ = rules.thresholds(60, fav_goals=goals)
        for k in config.KEYS:          # xg, shots, sot and box alike
            assert abs(vol[k] - (goals + 1) * base[k]) < 1e-9, (
                "%s wrong at %d goals" % (k, goals))
