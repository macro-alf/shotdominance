"""The request estimate must ERR HIGH against observed days.

Under-budgeting picks too fast a poll interval and spends the allowance early -
that is how the monitor went blind on 2026-08-16. Over-budgeting only costs a
slightly slower poll. These are the real days measured from the logs; 2026-08-16
is excluded because the monitor was blind that day, so its usage is not a
measurement of anything.
"""
import daily

# (label, fixtures, span_minutes, actual_requests_high_water)
OBSERVED = [
    ("2026-08-14", 21, 312, 2256),
    ("2026-08-15", 40, 660, 3845),
    ("2026-08-17", 6, 288, 878),
    ("2026-08-18", 3, 150, 598),
    ("2026-08-19", 5, 150, 645),
    ("2026-08-20", 37, 390, 3663),
]


def _estimate(n, span_min):
    base = 1_000_000
    pending = [(base + i * 60, "NS", None) for i in range(n)]
    start = base
    end = base + span_min * 60
    poll, est, _span, _peak = daily.pace(pending, start, end)
    return poll, est


def test_estimate_covers_every_observed_day():
    short = []
    for label, n, span, actual in OBSERVED:
        _poll, est = _estimate(n, span)
        if est < actual:
            short.append("%s: predicted %d, actually used %d" % (label, est, actual))
    assert not short, "pacing under-budgets:\n  " + "\n  ".join(short)


def test_estimate_is_not_absurdly_conservative():
    """Erring high is right; erring 3x high would throttle polling for nothing."""
    for label, n, span, actual in OBSERVED:
        _poll, est = _estimate(n, span)
        assert est < actual * 2.5, "%s over-estimates %dx" % (label, est // actual)


def test_a_heavy_night_still_fits_the_budget():
    """The 37-fixture night used ~half the allowance; twice that must still be
    plannable without exceeding it."""
    poll, est = _estimate(74, 480)
    assert est <= daily.DAILY_BUDGET - daily.QUOTA_RESERVE, (
        "74 fixtures estimated at %d, over budget" % est)


def test_halftime_is_counted_in_the_watched_span():
    """Watching is wall-clock; WATCH_FROM/WATCH_TO are elapsed match minutes."""
    assert daily.HALFTIME_MIN > 0
    _p, with_ht = _estimate(20, 300)
    original = daily.HALFTIME_MIN
    daily.HALFTIME_MIN = 0
    try:
        _p2, without_ht = _estimate(20, 300)
    finally:
        daily.HALFTIME_MIN = original
    assert with_ht > without_ht
