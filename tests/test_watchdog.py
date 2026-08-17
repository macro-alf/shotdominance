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
    assert watchdog.in_active_window(at(9))
    assert watchdog.in_active_window(at(23))
    assert watchdog.in_active_window(at(0))     # 00:xx, day still running
    assert not watchdog.in_active_window(at(4))
    assert not watchdog.in_active_window(at(7))
