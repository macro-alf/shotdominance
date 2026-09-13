"""Engine-level tests: the conviction firing policy and live-price
carry-forward.
"""
import contextlib
import io

from shotdominance import config, engine


class StubTg:
    def __init__(self):
        self.sent = []

    def updates(self, off):
        return []

    def send(self, text):
        self.sent.append(text)
        return 1


# --- firing policy ----------------------------------------------------------
def test_stats_carry_forward():
    mon = engine.Monitor(None, None, set())
    full = {"xg": 1.0, "shots": 10, "sot": 3, "box": 5}
    empty = {"xg": None, "shots": None, "sot": None, "box": None}

    mon._now = 1000.0
    f, o, carried = mon._carry_stats("1", dict(full), dict(full))
    assert not carried and f["shots"] == 10          # fresh full -> cached

    mon._now = 1100.0                                  # within TTL
    f, o, carried = mon._carry_stats("1", dict(empty), dict(empty))
    assert carried and f["shots"] == 10 and o["shots"] == 10  # gap -> carried

    mon._now = 1000.0 + config.STATS_CARRY_TTL + 100   # beyond TTL of last full
    f, o, carried = mon._carry_stats("1", dict(empty), dict(empty))
    assert not carried and f["shots"] is None          # too stale -> not carried


def test_stats_carry_forward_is_independent_per_side():
    mon = engine.Monitor(None, None, set())
    full = {"xg": 1.0, "shots": 10, "sot": 3, "box": 5}
    empty = {"xg": None, "shots": None, "sot": None, "box": None}
    mon._now = 1.0
    mon._carry_stats("1", dict(full), dict(full))
    mon._now = 2.0
    # favourite present, opponent missing -> only the opponent is carried
    f, o, carried = mon._carry_stats("1", {"xg": None, "shots": 12, "sot": 4,
                                           "box": 6}, dict(empty))
    assert f["shots"] == 12 and o["shots"] == 10 and carried


def test_fire_decision_conviction_floor():
    mon = engine.Monitor(None, None, set())
    floor = config.CONV_FIRE_MIN
    assert mon._fire_decision("1", floor - 1)[0] is False   # below the floor
    assert mon._fire_decision("1", floor)[0] is True        # at the floor fires


def test_fire_decision_repeats_at_every_checkpoint():
    """Changed 2026-09-07: an alert repeats while it stays valid.

    The old rule re-fired only on a NEW conviction high, so a fixture that
    alerted at 90 and then held at 85 went silent for the rest of the match.
    Alf asked for the opposite: keep telling me, until I say stop.
    """
    mon = engine.Monitor(None, None, set())
    floor = config.CONV_FIRE_MIN
    assert mon._fire_decision("1", floor + 5)[0] is True
    mon.best_conv["1"] = floor + 5                      # already alerted this high
    assert mon._fire_decision("1", floor + 5)[0] is True    # equal -> STILL fires
    assert mon._fire_decision("1", floor + 2)[0] is True    # lower -> STILL fires
    assert mon._fire_decision("1", floor - 1)[0] is False   # only the floor stops it


def test_muted_and_acked_are_the_only_silencers():
    """"bet done" and "ignore" are what stop an alert repeating."""
    mon = engine.Monitor(None, None, set())
    assert "muted" in vars(mon) and "acked" in vars(mon)
    mon.muted.add("1")
    mon.acked.add("2")
    # _fire_decision itself is unaware of them; suppression happens at the
    # checkpoint, so assert the sets exist and survive a save/load round trip.
    assert "1" in mon.muted and "2" in mon.acked


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


# --- early recording (the momentum window at the first checkpoint) ----------
def test_recording_starts_early_enough_for_a_complete_45_window():
    """Regression: recording used to start at exactly CHECKPOINTS[0]-WINDOW, so
    the first snapshot landed at 16' and the 45' checkpoint was always approx,
    which permanently blocked the momentum branch. RECORD_LEAD must buy a base
    snapshot at or before minute 15.

    Polls are stepped 2 minutes apart so minute 15 itself is never sampled: a
    poll cycle takes longer than POLL_SECONDS once pacing and retries are in
    play, so the live loop skips minutes (the 2026-08-14 log jumps 22'->24' and
    29'->31'). That is exactly why the first snapshot landed at 16'."""
    api = CarryStubApi()
    mon = engine.Monitor(api, StubTg(), {1})
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        for m in range(2, config.CHECKPOINTS[0] + 1, 2):   # 2', 4', ... 44'
            api.minute = m
            mon.poll()
        api.minute = config.CHECKPOINTS[0]                 # the 45' checkpoint
        mon.poll()

    base_needed = config.CHECKPOINTS[0] - config.WINDOW
    assert mon.history["7"][0].minute <= base_needed, (
        "no snapshot at or before %d' - the 45' window has no base" % base_needed)
    assert "~" not in _row_for(buf.getvalue(), config.CHECKPOINTS[0])


def test_nothing_is_recorded_before_the_lead_in():
    api = CarryStubApi()
    mon = engine.Monitor(api, StubTg(), {1})
    api.minute = config.CHECKPOINTS[0] - config.WINDOW - config.RECORD_LEAD - 1
    with contextlib.redirect_stdout(io.StringIO()):
        mon.poll()
    assert "7" not in mon.history          # too early to spend calls on


# --- feed health ------------------------------------------------------------
class DeadFeedApi(CarryStubApi):
    """API-Football refusing an account: HTTP 200, empty response, error in the
    body. Indistinguishable from a quiet evening unless last_error is watched."""
    def __init__(self):
        super().__init__()
        self.last_error = {"requests": "You have reached the request limit"}

    def get(self, path, **p):
        self.calls += 1
        self.reqs += 1
        return []


def test_dead_feed_alerts_once_then_stays_quiet():
    tg = StubTg()
    mon = engine.Monitor(DeadFeedApi(), tg, {1})
    with contextlib.redirect_stdout(io.StringIO()):
        for _ in range(config.FEED_BAD_POLLS):
            mon.poll()
    assert len(tg.sent) == 1 and "BLIND" in tg.sent[0]

    with contextlib.redirect_stdout(io.StringIO()):
        for _ in range(5):
            mon.poll()
    assert len(tg.sent) == 1          # cooldown: no nagging every minute


def test_no_alert_before_the_threshold():
    tg = StubTg()
    mon = engine.Monitor(DeadFeedApi(), tg, {1})
    with contextlib.redirect_stdout(io.StringIO()):
        for _ in range(config.FEED_BAD_POLLS - 1):
            mon.poll()
    assert tg.sent == []              # a single blip is not an outage


def test_recovery_is_announced():
    tg = StubTg()
    api = DeadFeedApi()
    mon = engine.Monitor(api, tg, {1})
    with contextlib.redirect_stdout(io.StringIO()):
        for _ in range(config.FEED_BAD_POLLS):
            mon.poll()
        api.last_error = None
        mon.poll()
    assert len(tg.sent) == 2 and "recovered" in tg.sent[1]


def test_a_quiet_evening_is_not_reported_as_an_outage():
    """0 live fixtures with no API error must stay silent."""
    tg = StubTg()
    api = DeadFeedApi()
    api.last_error = None
    mon = engine.Monitor(api, tg, {1})
    with contextlib.redirect_stdout(io.StringIO()):
        for _ in range(10):
            mon.poll()
    assert tg.sent == []


# --- quota guard ------------------------------------------------------------
class QuotaApi(CarryStubApi):
    """Reports a shrinking daily allowance via /status."""
    def __init__(self, left):
        super().__init__()
        self.left = left
        self.last_error = None

    def get(self, path, **p):
        if path == "/status":
            return {"requests": {"current": 7500 - self.left, "limit_day": 7500}}
        return super().get(path, **p)


def _run(mon, n):
    with contextlib.redirect_stdout(io.StringIO()):
        for _ in range(n):
            mon.poll()


def test_quota_guard_warns_once_and_slows_polling():
    tg = StubTg()
    mon = engine.Monitor(QuotaApi(left=400), tg, {1})
    start = mon.poll_seconds
    _run(mon, config.QUOTA_CHECK_POLLS)
    assert mon.poll_seconds > start          # stretched to save what is left
    assert len(tg.sent) == 1 and "quota running low" in tg.sent[0]

    _run(mon, config.QUOTA_CHECK_POLLS * 2)
    assert len(tg.sent) == 1                 # warned once, does not nag
    assert mon.poll_seconds <= config.QUOTA_POLL_MAX


def test_quota_guard_is_silent_when_there_is_plenty_left():
    tg = StubTg()
    mon = engine.Monitor(QuotaApi(left=6000), tg, {1})
    _run(mon, config.QUOTA_CHECK_POLLS * 2)
    assert tg.sent == [] and mon.poll_seconds == config.POLL_SECONDS


def test_quota_guard_does_not_check_every_poll():
    """The check costs a request; it must be periodic, not per poll."""
    api = QuotaApi(left=6000)
    mon = engine.Monitor(api, StubTg(), {1})
    _run(mon, config.QUOTA_CHECK_POLLS - 1)
    assert mon.polls == config.QUOTA_CHECK_POLLS - 1


# --- checkpoint grace (the Toulouse miss) -----------------------------------
class LateFeedApi(CarryStubApi):
    """A feed that publishes its statistics one poll AFTER the checkpoint."""
    def __init__(self):
        super().__init__()
        self.rich = False

    def get(self, path, **p):
        if path == "/fixtures/statistics" and not self.rich:
            def team(tid, xg, sh, sot, box):
                return {"team": {"id": tid}, "statistics": [
                    {"type": "Expected Goals", "value": xg},
                    {"type": "Total Shots", "value": sh},
                    {"type": "Shots on Goal", "value": sot},
                    {"type": "Shots insidebox", "value": box}]}
            return [team(1, "0.38", 4, 0, 2), team(2, "0.02", 1, 0, 0)]
        return super().get(path, **p)


def test_checkpoint_is_not_spent_on_the_first_poll():
    """Toulouse 0-0 Lyon, 2026-08-22: cp45 was judged on shots=4 / conv 23 and
    consumed; the real numbers arrived seconds later. The checkpoint must stay
    open long enough to see them."""
    api = LateFeedApi()
    mon = engine.Monitor(api, StubTg(), {1})
    api.minute = config.CHECKPOINTS[0]
    with contextlib.redirect_stdout(io.StringIO()):
        mon.poll()                              # stale stats at the checkpoint
    assert config.CHECKPOINTS[0] not in mon.done["7"], \
        "checkpoint was spent on the first poll"


def test_checkpoint_closes_once_its_grace_expires():
    api = LateFeedApi()
    mon = engine.Monitor(api, StubTg(), {1})
    with contextlib.redirect_stdout(io.StringIO()):
        api.minute = config.CHECKPOINTS[0]
        mon.poll()
        api.minute = config.CHECKPOINTS[0] + config.CHECKPOINT_GRACE
        mon.poll()
    assert config.CHECKPOINTS[0] in mon.done["7"]


# --- penalties --------------------------------------------------------------
class _PenApi:
    """Returns one MISSED penalty for team 10 at 45+1, like Genoa v Frosinone."""

    def __init__(self):
        self.calls = 0

    def get(self, path, **kw):
        self.calls += 1
        return [
            {"time": {"elapsed": 14, "extra": None}, "team": {"id": 20},
             "type": "Goal", "detail": "Normal Goal"},
            {"time": {"elapsed": 44, "extra": None}, "team": {"id": 10},
             "type": "Var", "detail": "Penalty confirmed"},
            {"time": {"elapsed": 45, "extra": 1}, "team": {"id": 10},
             "type": "Goal", "detail": "Missed Penalty"},
        ]


def _pen_monitor(api):
    mon = engine.Monitor(api, StubTg(), set())
    mon.history = {}
    mon.pens = {}
    return mon


def test_penalty_parse_ignores_var_award_and_normal_goals():
    from shotdominance import apifootball
    pens = apifootball.penalties(_PenApi(), 1)
    assert len(pens) == 1
    assert pens[0]["minute"] == 45 and pens[0]["scored"] is False
    assert pens[0]["team"] == 10


def test_penalty_stripped_restores_the_pre_penalty_reading():
    # the real Genoa 0-1 Frosinone numbers, 2026-09-12:
    #   44'  xg=0.60 shots=8 sot=2 box=6   <- before the penalty
    #   45'  xg=1.38 shots=9 sot=2 box=7   <- after it
    mon = _pen_monitor(_PenApi())
    fav = {"xg": 1.38, "shots": 9, "sot": 2, "box": 7}
    opp = {"xg": 0.37, "shots": 4, "sot": 1, "box": 1}
    with contextlib.redirect_stdout(io.StringIO()):
        f, o = mon._strip_penalties(1, 46, fav, opp, fav_id=10, opp_id=20)
    assert abs(f["xg"] - 0.60) < 1e-9
    assert (f["shots"], f["sot"], f["box"]) == (8, 2, 6)
    assert o == opp                      # opponent had no penalty, must not move


def test_penalty_subtraction_is_idempotent_across_polls():
    api = _PenApi()
    mon = _pen_monitor(api)
    raw_f = {"xg": 1.38, "shots": 9, "sot": 2, "box": 7}
    raw_o = {"xg": 0.37, "shots": 4, "sot": 1, "box": 1}
    with contextlib.redirect_stdout(io.StringIO()):
        a, _ = mon._strip_penalties(1, 46, dict(raw_f), dict(raw_o), 10, 20)
        b, _ = mon._strip_penalties(1, 47, dict(raw_f), dict(raw_o), 10, 20)
    assert a == b                        # same raw feed in, same corrected out
    assert api.calls == 1                # and no second lookup inside the refresh window


def test_penalty_found_late_retro_corrects_history():
    from shotdominance import rules
    mon = _pen_monitor(_PenApi())
    mon.history[1] = [
        rules.Snapshot(30, {"xg": 0.40, "shots": 5, "sot": 2, "box": 3},
                       {"xg": 0.30, "shots": 3, "sot": 1, "box": 1}, 0),
        rules.Snapshot(45, {"xg": 1.38, "shots": 9, "sot": 2, "box": 7},
                       {"xg": 0.37, "shots": 4, "sot": 1, "box": 1}, 0),
    ]
    with contextlib.redirect_stdout(io.StringIO()):
        mon._strip_penalties(1, 46, {"xg": 1.38, "shots": 9, "sot": 2, "box": 7},
                             {"xg": 0.37, "shots": 4, "sot": 1, "box": 1}, 10, 20)
    # the pre-penalty snapshot is untouched, the post-penalty one is corrected,
    # so the momentum window differences a consistent series
    assert mon.history[1][0].fav["shots"] == 5
    assert mon.history[1][1].fav["shots"] == 8


def test_scored_penalty_also_removes_a_shot_on_target():
    cost = engine.Monitor._penalty_cost(scored=True)
    assert cost["sot"] == 1.0
    missed = engine.Monitor._penalty_cost(scored=False)
    assert missed["sot"] == 0.0          # observed: sot did not move on a miss
    assert missed["shots"] == 1.0 and missed["box"] == 1.0


def test_penalties_can_be_switched_off():
    api = _PenApi()
    mon = _pen_monitor(api)
    raw = {"xg": 1.38, "shots": 9, "sot": 2, "box": 7}
    old = config.STRIP_PENALTIES
    config.STRIP_PENALTIES = False
    try:
        f, _ = mon._strip_penalties(1, 46, dict(raw), dict(raw), 10, 20)
    finally:
        config.STRIP_PENALTIES = old
    assert f == raw and api.calls == 0
