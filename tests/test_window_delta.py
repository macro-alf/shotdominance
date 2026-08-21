"""The momentum window must measure the LAST WINDOW minutes, never the match.

Regression for 2026-08-20 (Sion v Ajax): the feed published no statistics until
~minute 34, so the minute-15 baseline was all None. `prev.get(k) or 0` turned
that missing baseline into zero and the 45' "delta" equalled the full
cumulative total - momentum became a duplicate of volume, the 0-goals branch
fired on one piece of evidence while reporting two, and conviction hit 85.
"""
from shotdominance import config, rules

KEYS = config.KEYS


def snap(minute, fav, opp=None):
    return rules.Snapshot(minute, fav, opp or dict.fromkeys(KEYS, 0), 0)


def stats(xg=None, shots=None, sot=None, box=None):
    return {"xg": xg, "shots": shots, "sot": sot, "box": box}


def test_missing_baseline_is_unknown_not_zero():
    """The exact Ajax shape: nothing reported at 15', 13 shots by 45'."""
    hist = {"1": [snap(15, stats()), snap(45, stats(None, 13, 3, 7))]}
    cur = stats(None, 13, 3, 7)
    dfav, _dopp, approx = rules.window_delta(hist, "1", 45, cur, stats(None, 5, 0, 3))
    assert approx is True, "an empty baseline must be flagged, not trusted"
    # and it must NOT silently claim 13 shots happened in the last 30 minutes
    # while pretending the window was complete
    assert not (approx is False and dfav["shots"] == 13)


def test_partial_baseline_only_zeroes_what_it_knows():
    """shots known at the baseline, sot missing -> one real delta, one unknown."""
    hist = {"1": [snap(15, stats(None, 5, None, 2))]}
    cur = stats(None, 13, 3, 7)
    dfav, _d, approx = rules.window_delta(hist, "1", 45, cur, stats(None, 4, 1, 2))
    assert approx is False
    assert dfav["shots"] == 8          # 13 - 5, a genuine window measurement
    assert dfav["sot"] is None         # unknown at the baseline -> unknown now
    assert dfav["box"] == 5            # 7 - 2


def test_a_real_zero_baseline_is_still_zero():
    """A feed that genuinely reports 0 shots at 15' must keep working - the fix
    must not confuse 'reported zero' with 'not reported'."""
    hist = {"1": [snap(15, stats(0.0, 0, 0, 0))]}
    dfav, _d, approx = rules.window_delta(hist, "1", 45, stats(1.2, 13, 3, 7),
                                          stats(0.3, 5, 1, 2))
    assert approx is False
    assert dfav["shots"] == 13 and dfav["sot"] == 3 and dfav["box"] == 7


def test_empty_baseline_cannot_fire_the_zero_goal_branch():
    """End to end: the Ajax situation must no longer produce a signal, because
    the 0-goals branch needs momentum evidence and there is none."""
    hist = {"1": [snap(15, stats()), snap(45, stats(None, 13, 3, 7))]}
    ev = rules.evaluate(hist, "1", 45, stats(None, 13, 3, 7),
                        stats(None, 5, 0, 3), 0)
    assert ev.approx is True
    assert ev.ok is False, "an incomplete window must block the 0-goals branch"


def test_a_complete_window_still_fires():
    """The fix must not break the legitimate case it is protecting."""
    hist = {"1": [snap(15, stats(0.1, 2, 0, 1)), snap(45, stats(1.4, 14, 4, 8))]}
    ev = rules.evaluate(hist, "1", 45, stats(1.4, 14, 4, 8),
                        stats(0.2, 3, 1, 1), 0)
    assert ev.approx is False and ev.ok is True


# --- no alert without a real window ----------------------------------------
def test_scored_branch_cannot_fire_on_a_fabricated_window():
    """The (goals+1)x cumulative test used to fire with no momentum check at
    all. With an incomplete window the alert would print whole-match totals
    under a 'Last 30 min' heading - a bet invited on evidence never measured."""
    # no history at all -> no baseline -> approx
    cur = stats(3.0, 30, 9, 18)          # far over even a 2x bar
    ev = rules.evaluate({}, "1", 60, cur, stats(0.1, 2, 0, 1), 1)
    assert ev.approx is True
    assert ev.ok is False
    assert "BLOCKED" in ev.basis


def test_scored_branch_still_fires_with_a_real_window():
    hist = {"1": [snap(30, stats(0.2, 3, 1, 1)), snap(60, stats(3.0, 30, 9, 18))]}
    ev = rules.evaluate(hist, "1", 60, stats(3.0, 30, 9, 18),
                        stats(0.1, 2, 0, 1), 1)
    assert ev.approx is False and ev.ok is True


def test_the_ajax_situation_is_blocked_end_to_end():
    """Feed silent until minute 34: baseline at 15' all None, 13 shots by 45'.
    Fired at conviction 85 on 2026-08-20; must not fire now."""
    hist = {"1": [snap(15, stats()), snap(45, stats(None, 13, 3, 7))]}
    ev = rules.evaluate(hist, "1", 45, stats(None, 13, 3, 7),
                        stats(None, 5, 0, 3), 0)
    assert ev.ok is False and ev.approx is True
