"""Engine-level tests: the conviction firing policy and live-price
carry-forward.
"""
import contextlib
import io

from shotdominance import engine


class StubTg:
    def __init__(self):
        self.sent = []

    def updates(self, off):
        return []

    def send(self, text):
        self.sent.append(text)
        return 1


# --- firing policy ----------------------------------------------------------
def test_fire_decision_conviction_floor():
    mon = engine.Monitor(None, None, set())
    assert mon._fire_decision("1", 49)[0] is False    # below 50 floor
    assert mon._fire_decision("1", 50)[0] is True      # at the floor fires


def test_fire_decision_only_repeats_on_a_new_high():
    mon = engine.Monitor(None, None, set())
    assert mon._fire_decision("1", 55)[0] is True
    mon.best_conv["1"] = 55                            # record the alerted high
    assert mon._fire_decision("1", 55)[0] is False     # equal -> no repeat
    assert mon._fire_decision("1", 52)[0] is False     # lower -> no repeat
    assert mon._fire_decision("1", 60)[0] is True      # higher -> repeats


# --- price carry-forward ----------------------------------------------------
class CarryStubApi:
    def __init__(self):
        self.calls = self.reqs = 0
        self.throttled = 0.0
        self.retries = 0
        self.have_odds = True
        self.minute = 70

    def get(self, path, **p):
        self.calls += 1
        self.reqs += 1
        if path == "/odds/live":
            if not self.have_odds:
                return []
            return [{"fixture": {"id": 7}, "status": {}, "odds": [
                {"name": "Match Winner", "values": [
                    {"value": "Home", "odd": "2.0"},
                    {"value": "Away", "odd": "3.5"},
                    {"value": "Draw", "odd": "3.2"}]}]}]
        if path == "/fixtures" and p.get("live") == "all":
            return [{"league": {"id": 1, "name": "L"},
                     "fixture": {"id": 7, "status": {"elapsed": self.minute}},
                     "teams": {"home": {"id": 1, "name": "H"},
                               "away": {"id": 2, "name": "A"}},
                     "goals": {"home": 1, "away": 1}}]   # favourite level (1-1)
        if path == "/odds":
            return [{"bookmakers": [{"bets": [{"name": "Match Winner", "values": [
                {"value": "Home", "odd": "1.8"}, {"value": "Away", "odd": "4.0"}]}]}]}]
        if path == "/fixtures/statistics":
            def team(tid, xg, sh, sot, box):
                return {"team": {"id": tid}, "statistics": [
                    {"type": "Expected Goals", "value": xg},
                    {"type": "Total Shots", "value": sh},
                    {"type": "Shots on Goal", "value": sot},
                    {"type": "Shots insidebox", "value": box}]}
            return [team(1, "1.6", 26, 6, 14), team(2, "0.3", 4, 1, 2)]
        return []


def _row_for(out, minute):
    for line in out.splitlines():
        if (" %d'" % minute) in line and "odds=" in line:
            return line
    return ""


def test_price_carry_forward_survives_a_blocked_poll():
    api = CarryStubApi()
    mon = engine.Monitor(api, StubTg(), {1})
    mon.history["7"] = [engine.rules.Snapshot(
        40, {"xg": 0.3, "shots": 8, "sot": 1, "box": 3},
        {"xg": 0.2, "shots": 3, "sot": 1, "box": 1}, 1)]

    # poll 1: odds present -> cached
    api.minute = 70
    with contextlib.redirect_stdout(io.StringIO()):
        mon.poll()
    assert "7" in mon.price_cache

    # poll 2 at a new checkpoint: odds blocked -> the row must still carry a price
    api.have_odds = False
    api.minute = 75
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        mon.poll()
    row = _row_for(buf.getvalue(), 75)
    assert "odds=n/a" not in row and "odds=2.0" in row  # carried the Home price


def test_carry_forward_expires_after_ttl():
    from shotdominance import config
    api = CarryStubApi()
    mon = engine.Monitor(api, StubTg(), {1})
    mon.history["7"] = [engine.rules.Snapshot(
        40, {"xg": 0.3, "shots": 8, "sot": 1, "box": 3},
        {"xg": 0.2, "shots": 3, "sot": 1, "box": 1}, 1)]
    api.minute = 70
    with contextlib.redirect_stdout(io.StringIO()):
        mon.poll()
    # force the cached entry to look stale, then a blocked poll must NOT reuse it
    ts, d = mon.price_cache["7"]
    mon.price_cache["7"] = (ts - config.PRICE_CARRY_TTL - 10, d)
    api.have_odds = False
    api.minute = 75
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        mon.poll()
    assert "odds=n/a" in _row_for(buf.getvalue(), 75)
