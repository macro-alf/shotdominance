"""The sleeper must never suspend the machine outside the small hours.

Registered with StartWhenAvailable, the 23:30 task fired ~10 minutes after the
morning wake - Task Scheduler treats a window slept through as missed - and
suspended the PC on three consecutive mornings (26-28 Sep 2026). The task
setting was removed; this guard is what makes it impossible.
"""
import datetime as dt

import sleeper


def at(hour, minute=0):
    return dt.datetime(2026, 9, 28, hour, minute)


def test_the_morning_is_never_a_sleep_window():
    # the exact failure: fired at 08:54 and suspended the PC
    for hour in range(3, 23):
        assert not sleeper.in_window(at(hour)), "would suspend at %02d:00" % hour


def test_the_night_is():
    for hour in (23, 0, 1, 2):
        assert sleeper.in_window(at(hour)), "would refuse at %02d:00" % hour


def test_boundaries():
    assert not sleeper.in_window(at(22, 59))
    assert sleeper.in_window(at(23, 0))
    assert sleeper.in_window(at(2, 59))
    assert not sleeper.in_window(at(3, 0))
