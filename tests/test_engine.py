"""Engine-level tests: the conviction firing policy and live-price
carry-forward.
"""
import contextlib
import io

from shotdominance import config, engine, rules, sizing


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


def test_a_superseded_checkpoint_cannot_be_held_open():
    """Why the 2026-09-20 "hold a blind checkpoint open" idea was abandoned:
    due_checkpoint() retires every reached-but-lower checkpoint, so once the
    clock passes the next one the earlier one is judged no matter what the
    caller decides. With checkpoints 5 apart and grace 4 there is at most one
    minute of room, so holding a checkpoint open buys nothing."""
    done = set()
    assert rules.due_checkpoint(done, config.CHECKPOINTS[1]) == config.CHECKPOINTS[1]
    assert config.CHECKPOINTS[0] in done


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


# --- adaptive polling -------------------------------------------------------
def _slow_monitor(quota_frac=None):
    """A monitor with adaptive polling ARMED, i.e. the day's quota already past
    SLOW_POLL_FROM_QUOTA. Below that threshold nothing is ever skipped, so the
    tiering tests have to put it in the state where tiering applies."""
    mon = engine.Monitor(None, None, set())
    mon.last_conv = {}
    mon.polls = 1
    mon.quota_frac = (config.SLOW_POLL_FROM_QUOTA + 0.10
                      if quota_frac is None else quota_frac)
    return mon


def test_unmeasured_fixture_is_always_polled():
    mon = _slow_monitor()
    assert mon._due_for_poll("new", 33) is True


def test_dull_fixture_is_polled_less_often():
    mon = _slow_monitor()
    mon.last_conv["dull"] = 15.0            # below SLOW_POLL_LOW_CONV
    polled = [p for p in range(1, 13)
              if (setattr(mon, "polls", p) or mon._due_for_poll("dull", 33))]
    assert len(polled) == 12 // config.SLOW_POLL_LOW_EVERY


def test_promising_fixture_is_polled_every_cycle():
    mon = _slow_monitor()
    mon.last_conv["good"] = 70.0
    for p in range(1, 8):
        mon.polls = p
        assert mon._due_for_poll("good", 33) is True


def test_a_checkpoint_window_is_never_skipped():
    # otherwise a dull fixture could miss the only moment it is judged, and its
    # conviction would never refresh to escape the slow tier
    mon = _slow_monitor()
    mon.last_conv["dull"] = 5.0
    for cp in config.CHECKPOINTS:
        for m in range(cp, cp + config.CHECKPOINT_GRACE + 1):
            mon.polls = 3                    # a cycle it would otherwise skip
            assert mon._due_for_poll("dull", m) is True, (cp, m)


def test_slow_poll_can_be_switched_off():
    mon = _slow_monitor()
    mon.last_conv["dull"] = 5.0
    old = config.SLOW_POLL
    config.SLOW_POLL = False
    try:
        mon.polls = 3
        assert mon._due_for_poll("dull", 33) is True
    finally:
        config.SLOW_POLL = old


def test_nothing_is_skipped_while_the_quota_is_healthy():
    # Alf 2026-09-14: the slow tiers are a RESCUE. They were throttling from the
    # first poll of the day - Inter 0-2 down to Udinese, a 1.18 pre-match
    # favourite, got 3 statistics calls in 21 minutes on 15% quota.
    mon = _slow_monitor(quota_frac=0.0)
    mon.last_conv["dull"] = 5.0
    assert all(mon._due_for_poll("dull", 33) for _ in range(12))
    mon.quota_frac = config.SLOW_POLL_FROM_QUOTA - 0.01
    assert mon._due_for_poll("dull", 33) is True


def test_skipping_starts_once_the_quota_threshold_is_crossed():
    mon = _slow_monitor(quota_frac=config.SLOW_POLL_FROM_QUOTA)
    mon.last_conv["dull"] = 15.0
    polled = [p for p in range(1, 13)
              if (setattr(mon, "polls", p) or mon._due_for_poll("dull", 33))]
    assert len(polled) == 12 // config.SLOW_POLL_LOW_EVERY


def test_a_checkpoint_window_is_never_skipped_even_when_armed():
    mon = _slow_monitor()
    mon.last_conv["dull"] = 1.0
    mon.polls = 3                                # not a multiple of LOW_EVERY
    assert mon._due_for_poll("dull", config.CHECKPOINTS[0]) is True


def _edge_monitor():
    mon = engine.Monitor(None, None, set())
    return mon


def test_a_quote_within_tolerance_of_the_requirement_now_fires():
    # Alf 2026-09-19: fire when the price comes within EDGE_TOLERANCE of the
    # bar instead of refusing, and say so in the alert.
    need = 2.50
    tol = config.EDGE_TOLERANCE
    assert (need - tol + 0.01) >= need - tol      # just inside -> fires
    assert not (need - tol - 0.01) >= need - tol  # just outside -> refused


def test_the_tolerance_lowers_the_effective_floor():
    # `need` is max(break-even, MIN_BACKABLE_ODDS), so the tolerance applies to
    # the floor too: the shortest backable price is really 1.80 - 0.20 = 1.60.
    # Pinned so the consequence cannot be forgotten - raise MIN_BACKABLE_ODDS if
    # 1.80 was meant as a hard minimum.
    floor = config.MIN_BACKABLE_ODDS
    assert round(floor - config.EDGE_TOLERANCE, 2) == 1.60


def test_a_sub_requirement_alert_says_the_price_is_short():
    mon = _edge_monitor()
    ctx = dict(label="A 0-0 B", league="L", minute=60, fav="A", side="home",
               score="0-0", conv=72.0, price=2.35, market="win", kind="k",
               derived=False, need=2.50, state="level", winp=0.44, pm=1.60,
               short_by=0.15)

    ev = rules.Evaluation(
        ok=True, basis="0 goals: volume AND momentum", approx=False, win_min=30,
        cum_dom=3, opp_leads=0, conv=72.0, vol_met=3, mom_met=3, n_present=4,
        vol_det=["shots 18/12"], mom_det=["shots +9"], extra=[], s_vol=80.0,
        s_mom=75.0, s_dom=60.0, s_time=40.0, time_mult=1.0, vol_th={}, mom_th={})
    sz = sizing.size(2.50, 72.0)
    txt = mon.alert_text(ctx, ev, sz, 2.35, 1.60)
    assert "SHORT OF THE MINIMUM" in txt
    assert "2.50" in txt and "2.35" in txt
    assert "NO modelled edge" in txt


def test_a_price_at_or_above_the_requirement_carries_no_short_warning():
    mon = _edge_monitor()
    ctx = dict(label="A 0-0 B", league="L", minute=60, fav="A", side="home",
               score="0-0", conv=72.0, price=2.80, market="win", kind="k",
               derived=False, need=2.50, state="level", winp=0.44, pm=1.60,
               short_by=0.0)

    ev = rules.Evaluation(
        ok=True, basis="0 goals: volume AND momentum", approx=False, win_min=30,
        cum_dom=3, opp_leads=0, conv=72.0, vol_met=3, mom_met=3, n_present=4,
        vol_det=["shots 18/12"], mom_det=["shots +9"], extra=[], s_vol=80.0,
        s_mom=75.0, s_dom=60.0, s_time=40.0, time_mult=1.0, vol_th={}, mom_th={})
    sz = sizing.size(2.50, 72.0)
    txt = mon.alert_text(ctx, ev, sz, 2.80, 1.60)
    assert "SHORT OF THE MINIMUM" not in txt


def _quote_monitor(monkeypatch=None):
    """A monitor with the quote band FORCED ON. It ships disabled (see the
    post-mortem at config.QUOTE_CONFIRM) but the logic is kept for the rebuild,
    so these tests still pin its behaviour."""
    mon = engine.Monitor(None, None, set())
    mon._now = 1000.0
    config.QUOTE_SANITY = True
    return mon


def test_the_quote_band_ships_disabled():
    """2026-09-20: live for eight hours, discarded 96 quotes across 68 fixtures
    because A GOAL LEGITIMATELY MOVES A PRICE BY MORE THAN 40% and the band
    cannot see the scoreline. It also inverted on Gostepe - accepted a
    double-chance quote of 1.22 as the reference, then rejected the genuine 3.40
    and fired a signal unsized that should have been sized. Off until the
    rebuild anchors plausibility on pre-match price and scoreline."""
    import importlib
    from shotdominance import config as fresh
    importlib.reload(fresh)
    assert fresh.QUOTE_SANITY is False, "the band must not ship enabled again"


def test_the_sunderland_misquote_is_rejected():
    # 2026-09-19: 2.20 -> feed gap -> 1.14, score and evidence unchanged. A
    # different market landing in the win slot, not a price move.
    mon = _quote_monitor()
    assert mon._sane_price("f", 2.20) == 2.20
    mon._now += 120
    assert mon._sane_price("f", 1.14) is None, "a 48% jump is not a price move"


def test_a_real_price_drift_still_passes():
    # Athletic Club 2026-09-19 moved 1.95 -> 3.00 over 23 minutes in steps; each
    # step must pass or the gate goes blind on an honest market.
    mon = _quote_monitor()
    for p in (1.95, 2.10, 2.40, 2.75, 3.00):
        mon._now += 300
        assert mon._sane_price("f", p) == p, "rejected a genuine drift to %.2f" % p


def test_a_long_price_on_a_dying_match_is_not_rejected_for_its_level():
    # only MOVEMENT is tested. A first sighting at 18.00 is real information.
    mon = _quote_monitor()
    assert mon._sane_price("f", 18.31) == 18.31


def test_a_stale_reference_does_not_veto_a_later_quote():
    mon = _quote_monitor()
    mon._sane_price("f", 2.20)
    mon._now += config.QUOTE_JUMP_WINDOW + 1
    assert mon._sane_price("f", 1.14) == 1.14, "reference older than the window"


def test_a_rejected_quote_does_not_become_the_new_reference():
    mon = _quote_monitor()
    mon._sane_price("f", 2.20)
    mon._now += 60
    assert mon._sane_price("f", 1.14) is None
    mon._now += 60
    assert mon._sane_price("f", 2.30) == 2.30, "2.20 must still be the reference"


def test_a_sustained_move_is_accepted_once_it_holds():
    """Energie Cottbus v St. Pauli, 2026-09-20: 2.30 -> 4.33 -> 4.75 -> 5.00 and
    it stayed there. The first version of the band rejected the jump and then
    every later poll, because a rejected quote never refreshed the reference -
    the fixture was left permanently unpriced. A mis-map flickers; a real move
    holds."""
    mon = _quote_monitor()
    assert mon._sane_price("f", 2.30) == 2.30
    mon._now += 80
    assert mon._sane_price("f", 4.33) is None, "first sighting is held back"
    mon._now += 80
    assert mon._sane_price("f", 4.75) == 4.75, "it held - accept the real move"
    mon._now += 80
    assert mon._sane_price("f", 5.00) == 5.00, "reference has moved with it"


def test_a_flickering_misquote_is_still_refused():
    # the Sunderland shape: one bad print, then back to the real level.
    mon = _quote_monitor()
    mon._sane_price("f", 2.20)
    mon._now += 60
    assert mon._sane_price("f", 1.14) is None
    mon._now += 60
    assert mon._sane_price("f", 2.25) == 2.25, "the real price returns untouched"
    mon._now += 60
    assert mon._sane_price("f", 1.14) is None, "and the bad one is refused again"


def test_the_alert_context_survives_a_restart():
    """2026-09-20: the monitor was restarted between the Wolves alert and Alf's
    reply. `last_alert` was memory-only, so record_bet built a row with no
    match, no back and no side - and settle_bet grades from `side`, so it would
    have settled as the wrong team. The row had to be repaired by hand."""
    mon = engine.Monitor(None, StubTg(), set())
    mon.last_alert["1563177"] = {"label": "Wolves 0-0 West Brom", "fav": "Wolves",
                                 "side": "home", "market": "win"}
    mon.awaiting["chat"] = "1563177"
    mon.save()
    fresh = engine.Monitor(None, StubTg(), set())
    fresh.load()
    assert fresh.last_alert.get("1563177", {}).get("label") == "Wolves 0-0 West Brom"
    assert fresh.last_alert["1563177"]["side"] == "home"


def test_data_losses_are_counted_not_just_survived():
    """2026-09-19/20: three times in a week the answer to "why did nothing
    fire?" was a silent data loss nobody counted - an API timeout that broke a
    momentum window (Aris, 21 shots to 2, lost cp60 and cp65), a fixture the
    feed never described (Fenerbahce, vol 0/0 for ninety minutes), and a bulk
    odds outage that blinded every watched fixture at once."""
    mon = engine.Monitor(None, None, set())
    assert set(mon.lost) == {"no_window", "no_stats", "no_price", "feed_fail"}
    assert all(v == 0 for v in mon.lost.values())


def test_the_loss_line_is_silent_when_nothing_was_lost():
    mon = engine.Monitor(None, None, set())
    lost = ", ".join("%s %d" % (k, v) for k, v in sorted(mon.lost.items()) if v)
    assert lost == "", "a clean poll must not print a losses line"
    mon.lost["no_window"] = 3
    lost = ", ".join("%s %d" % (k, v) for k, v in sorted(mon.lost.items()) if v)
    assert lost == "no_window 3"
