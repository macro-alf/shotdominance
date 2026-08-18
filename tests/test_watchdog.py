"""The watchdog is the only thing that can notice the supervisor dying, so its
decision logic has to be right: silent when nothing is wrong, loud when the day
is live and the supervisor has stopped, and quiet about deliberate exits.
"""
import datetime as dt

import watchdog


def _write(tmp_path, monkeypatch, stamp, state):
    p = tmp_path / "heartbeat.txt"
    p.write_text("%s %s\n" % (stamp.isoformat(timespec="seconds"), state),
                 encoding="utf-8")
    monkeypatch.setattr(watchdog, "HEARTBEAT", str(p))


def _active(monkeypatch):
    monkeypatch.setattr(watchdog, "in_active_window", lambda now=None: True)


def test_fresh_heartbeat_is_ok(tmp_path, monkeypatch):
    _active(monkeypatch)
    _write(tmp_path, monkeypatch, dt.datetime.now(), "waiting-for-launch")
    assert watchdog.diagnose()[0] is None


def test_stale_heartbeat_is_a_problem(tmp_path, monkeypatch):
    _active(monkeypatch)
    _write(tmp_path, monkeypatch,
           dt.datetime.now() - dt.timedelta(minutes=watchdog.STALE_MIN + 5),
           "waiting-for-launch")
    problem, detail = watchdog.diagnose()
    assert problem == "stale heartbeat" and "waiting-for-launch" in detail


def test_deliberate_exit_is_not_a_problem(tmp_path, monkeypatch):
    """'finished' and 'aborted' mean daily.py meant to stop. Treating those as
    failures would restart the day every night after the PC sleeps."""
    _active(monkeypatch)
    for state in ("finished", "aborted"):
        _write(tmp_path, monkeypatch,
               dt.datetime.now() - dt.timedelta(hours=6), state)
        assert watchdog.diagnose()[0] is None, state


def test_missing_heartbeat_is_a_problem(tmp_path, monkeypatch):
    _active(monkeypatch)
    monkeypatch.setattr(watchdog, "HEARTBEAT", str(tmp_path / "nope.txt"))
    assert watchdog.diagnose()[0] == "no heartbeat"


def test_nothing_fires_outside_the_active_window(tmp_path, monkeypatch):
    monkeypatch.setattr(watchdog, "in_active_window", lambda now=None: False)
    monkeypatch.setattr(watchdog, "HEARTBEAT", str(tmp_path / "nope.txt"))
    assert watchdog.diagnose()[0] is None


def test_active_window_spans_midnight():
    at = lambda h: dt.datetime(2026, 8, 17, h, 0)
    assert watchdog.in_active_window(at(11))
    assert watchdog.in_active_window(at(23))
    assert watchdog.in_active_window(at(0))     # 00:xx, day still running
    assert not watchdog.in_active_window(at(4))
    assert not watchdog.in_active_window(at(9))   # PC may not be awake yet


# --- the 2026-08-18 blind spot ---------------------------------------------
def _write_dated(tmp_path, monkeypatch, when, state):
    p = tmp_path / "heartbeat.txt"
    p.write_text("%s %s\n" % (when.isoformat(timespec="seconds"), state),
                 encoding="utf-8")
    monkeypatch.setattr(watchdog, "HEARTBEAT", str(p))


def test_yesterdays_finished_during_the_active_window_is_a_problem(tmp_path,
                                                                   monkeypatch):
    """Regression: on 2026-08-18 the 08:00 task missed its run while the PC
    slept. The heartbeat still read 'finished' from 23:25 the night before, so
    the watchdog treated it as a deliberate stop and said nothing all morning."""
    now = dt.datetime(2026, 8, 18, 10, 30)
    _write_dated(tmp_path, monkeypatch, dt.datetime(2026, 8, 17, 23, 25), "finished")
    problem, detail = watchdog.diagnose(now=now)
    assert problem == "supervisor never started today"
    assert "2026-08-17" in detail


def test_todays_finished_is_still_fine(tmp_path, monkeypatch):
    """daily.py legitimately exits early when there are no fixtures - that must
    not be mistaken for a missed start."""
    now = dt.datetime(2026, 8, 18, 11, 0)
    _write_dated(tmp_path, monkeypatch, dt.datetime(2026, 8, 18, 9, 10), "finished")
    assert watchdog.diagnose(now=now)[0] is None


def test_last_nights_finished_just_after_midnight_is_fine(tmp_path, monkeypatch):
    """00:30 is inside the active window but before the morning start, so
    yesterday's clean finish is correct, not a missed run."""
    now = dt.datetime(2026, 8, 18, 0, 30)
    _write_dated(tmp_path, monkeypatch, dt.datetime(2026, 8, 17, 23, 25), "finished")
    assert watchdog.diagnose(now=now)[0] is None
