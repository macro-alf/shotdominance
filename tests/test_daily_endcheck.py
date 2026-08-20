"""The day only ends on POSITIVE evidence that every tracked fixture is done.

apifootball.ApiClient.get() returns [] on any failure, so a failed or short
schedule response must never be read as "all finished" - that shut the monitor
down on 2026-08-19 while two matches were still at 85' and 90'.
"""
import daily

DONE = daily.DONE_STATUS


def _rows(statuses):
    """Shape todays_fixtures() returns: (timestamp, status_short, fixture)."""
    return [(1000 + i, st, {"teams": {"home": {"name": "H%d" % i}}})
            for i, st in enumerate(statuses)]


def decide(rest, pending_n):
    """The end-check rule, mirrored: -> 'finished' | 'unknown' | 'in-play'."""
    if len(rest) < pending_n:
        return "unknown"
    return "in-play" if [x for x in rest if x[1] not in DONE] else "finished"


def test_empty_response_is_unknown_not_finished():
    assert decide(_rows([]), 5) == "unknown"


def test_short_response_is_unknown():
    """Two of five fixtures came back - the other three are unaccounted for."""
    assert decide(_rows(["FT", "FT"]), 5) == "unknown"


def test_all_present_and_done_finishes_the_day():
    assert decide(_rows(["FT", "FT", "AET", "PEN", "FT"]), 5) == "finished"


def test_one_still_in_play_keeps_going():
    assert decide(_rows(["FT", "FT", "2H", "FT", "FT"]), 5) == "in-play"


def test_postponed_and_cancelled_count_as_done():
    assert decide(_rows(["FT", "PST", "CANC", "ABD", "WO"]), 5) == "finished"
