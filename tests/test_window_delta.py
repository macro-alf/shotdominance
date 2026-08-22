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
    dfav, _dopp, approx, _w = rules.window_delta(hist, "1", 45, cur, stats(None, 5, 0, 3))
    assert approx is True, "an empty baseline must be flagged, not trusted"
    # and it must NOT silently claim 13 shots happened in the last 30 minutes
    # while pretending the window was complete
    assert not (approx is False and dfav["shots"] == 13)


def test_partial_baseline_only_zeroes_what_it_knows():
    """shots known at the baseline, sot missing -> one real delta, one unknown."""
    hist = {"1": [snap(15, stats(None, 5, None, 2))]}
    cur = stats(None, 13, 3, 7)
    dfav, _d, approx, _w = rules.window_delta(hist, "1", 45, cur, stats(None, 4, 1, 2))
    assert approx is False
    assert dfav["shots"] == 8          # 13 - 5, a genuine window measurement
    assert dfav["sot"] is None         # unknown at the baseline -> unknown now
    assert dfav["box"] == 5            # 7 - 2


def test_a_real_zero_baseline_is_still_zero():
    """A feed that genuinely reports 0 shots at 15' must keep working - the fix
    must not confuse 'reported zero' with 'not reported'."""
    hist = {"1": [snap(15, stats(0.0, 0, 0, 0))]}
    dfav, _d, approx, _w = rules.window_delta(hist, "1", 45, stats(1.2, 13, 3, 7),
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


# --- variable window (feeds that publish late) ------------------------------
def late_feed(first_stats_min, upto, final=None):
    """History for a fixture whose feed reports nothing until first_stats_min,
    then accumulates linearly to `final` by `upto` - as real counters do."""
    final = final or stats(0.8, 13, 2, 8)
    span = max(upto - first_stats_min, 1)
    out = []
    for m in range(10, upto + 1):
        if m < first_stats_min:
            out.append(snap(m, stats()))
            continue
        f = (m - first_stats_min) / span
        out.append(snap(m, stats(round(final["xg"] * f, 3),
                                 int(final["shots"] * f),
                                 int(final["sot"] * f),
                                 int(final["box"] * f))))
    return out


def test_uses_the_longest_window_the_feed_supports():
    """Dundalk v Galway 2026-08-21: silent until 26', checkpoint at 50'. The
    full 30-min window has no baseline, but 24 real minutes do exist."""
    hist = {"1": late_feed(26, 50)}
    dfav, _d, approx, win = rules.window_delta(
        hist, "1", 50, stats(0.8, 13, 2, 8), stats(0.23, 3, 2, 3))
    assert approx is False
    assert win == 24, "should measure 50' - 26' = 24 real minutes"


def test_window_shorter_than_the_minimum_is_refused():
    """Feed starts at 35' with a 50' checkpoint -> only 15 minutes, below
    MIN_WINDOW. Too short a sample is not momentum."""
    hist = {"1": late_feed(35, 50)}
    _f, _d, approx, win = rules.window_delta(
        hist, "1", 50, stats(0.8, 13, 2, 8), stats(0.23, 3, 2, 3))
    assert approx is True and win == 0


def test_a_full_window_is_still_preferred_when_available():
    hist = {"1": late_feed(10, 50)}
    _f, _d, approx, win = rules.window_delta(
        hist, "1", 50, stats(0.8, 13, 2, 8), stats(0.23, 3, 2, 3))
    assert approx is False and win == config.WINDOW


def test_the_bar_scales_with_the_measured_window():
    """A 20-minute window judged against a 30-minute bar would never pass."""
    _v30, mom30 = rules.thresholds(50, 30)
    _v20, mom20 = rules.thresholds(50, 20)
    assert mom20["shots"] < mom30["shots"]
    assert abs(mom20["shots"] / mom30["shots"] - 20.0 / 30.0) < 1e-9


def test_dundalk_now_fires_on_its_real_24_minute_window():
    """The checkpoint that was blocked outright on 2026-08-21."""
    hist = {"1": late_feed(26, 50)}
    ev = rules.evaluate(hist, "1", 50, stats(0.8, 13, 2, 8),
                        stats(0.23, 3, 2, 3), 0)
    assert ev.win_min == 24 and not ev.approx and ev.ok


# --- the window is ALWAYS the last WINDOW minutes ---------------------------
def test_window_never_exceeds_the_nominal_length():
    """A baseline older than WINDOW would measure more than 30 minutes of
    football and call it momentum. Sparse history must not sneak one in."""
    hist = {"x": [snap(10, stats(0.1, 2, 1, 1)), snap(50, stats(0.9, 14, 4, 9))]}
    _d, _o, approx, win = rules.window_delta(
        hist, "x", 50, stats(0.9, 14, 4, 9), stats(0.2, 3, 1, 2))
    assert win <= config.WINDOW
    assert approx is True and win == 0, "40 minutes back is not a 30-min window"


def test_full_window_preferred_over_a_shorter_one_that_also_fits():
    """Baselines at both 20' and 25' for a 50' checkpoint -> take 20' (30 min)."""
    hist = {"x": [snap(20, stats(0.1, 2, 1, 1)), snap(25, stats(0.2, 4, 1, 2)),
                  snap(50, stats(0.9, 14, 4, 9))]}
    _d, _o, approx, win = rules.window_delta(
        hist, "x", 50, stats(0.9, 14, 4, 9), stats(0.2, 3, 1, 2))
    assert not approx and win == config.WINDOW


def test_window_stays_inside_the_band_for_every_checkpoint():
    """Property check across a late feed and all checkpoints."""
    for first in (10, 20, 26, 31, 38):
        hist = {"x": late_feed(first, 75)}
        for cp in config.CHECKPOINTS:
            h = {"x": [s for s in hist["x"] if s.minute <= cp]}
            _d, _o, approx, win = rules.window_delta(
                h, "x", cp, stats(0.9, 14, 4, 9), stats(0.2, 3, 1, 2))
            assert approx or config.MIN_WINDOW <= win <= config.WINDOW, (
                "first=%d cp=%d gave win=%d" % (first, cp, win))
