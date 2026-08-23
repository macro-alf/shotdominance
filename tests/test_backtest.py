"""Phase-1 backtest: reconstruction, gating and settlement.

All pure - no network. The fetchers are exercised by running the backtest; what
needs guarding is the arithmetic that turns shots into snapshots, because an
error there would silently produce a plausible-looking but wrong edge.
"""
from backtest import reconstruct, replay
from shotdominance import config


def shot(minute, side, result="MissedShots", xg=0.1, x=0.90, y=0.5):
    return {"minute": str(minute), "result": result, "xG": str(xg),
            "X": str(x), "Y": str(y), "h_a": side}


# --- reconstruction ---------------------------------------------------------
def test_metrics_accumulate_and_are_cumulative():
    shots = {"h": [shot(10, "h", "SavedShot"), shot(20, "h", "Goal"),
                   shot(30, "h", "BlockedShot")],
             "a": [shot(15, "a")]}
    series, goals = reconstruct.build(shots)

    assert series["h"][9]["shots"] == 0
    assert series["h"][10]["shots"] == 1
    assert series["h"][25]["shots"] == 2          # cumulative, holds between shots
    assert series["h"][40]["shots"] == 3
    # on target = Goal + SavedShot; BlockedShot and MissedShots are not
    assert series["h"][40]["sot"] == 2
    assert series["a"][40]["sot"] == 0
    assert abs(series["h"][40]["xg"] - 0.3) < 1e-9
    assert goals["h"][19] == 0 and goals["h"][20] == 1


def test_no_lookahead_at_the_checkpoint_boundary():
    """The one bug that would manufacture an edge out of nothing: a snapshot at
    minute m must contain everything up to and including m, and NOTHING after.
    A single minute of leakage at the 45' checkpoint would let the rule see
    shots that had not been taken yet."""
    shots = {"h": [shot(44, "h", "Goal"), shot(45, "h", "SavedShot"),
                   shot(46, "h", "Goal"), shot(70, "h")],
             "a": []}
    series, goals = reconstruct.build(shots)

    assert series["h"][45]["shots"] == 2        # minutes 44 and 45 only
    assert series["h"][45]["sot"] == 2
    assert goals["h"][45] == 1                  # the 46' goal has not happened
    assert series["h"][46]["shots"] == 3 and goals["h"][46] == 2

    # and the history handed to the rule engine stops at the checkpoint
    hist = reconstruct.history_to(series, goals, "h", 45)
    assert max(s.minute for s in hist) == 45
    assert all(s.fav["shots"] <= 2 for s in hist)


def test_shot_on_post_is_not_on_target():
    series, _ = reconstruct.build({"h": [shot(10, "h", "ShotOnPost")], "a": []})
    assert series["h"][20]["shots"] == 1 and series["h"][20]["sot"] == 0


def test_own_goal_counts_for_the_opponent():
    """Understat records an own goal against the team that took the shot; it is
    a goal FOR the other side. Getting this backwards would corrupt the score
    timeline and therefore every level/behind gate."""
    series, goals = reconstruct.build({"h": [shot(30, "h", "OwnGoal", xg=0.0)],
                                       "a": []})
    assert goals["a"][40] == 1 and goals["h"][40] == 0
    assert series["h"][40]["shots"] == 1      # the shot still belongs to the shooter


def test_box_detection_uses_the_penalty_area():
    inside = reconstruct.build({"h": [shot(10, "h", x=0.90, y=0.5)], "a": []})[0]
    outside_x = reconstruct.build({"h": [shot(10, "h", x=0.70, y=0.5)], "a": []})[0]
    wide_y = reconstruct.build({"h": [shot(10, "h", x=0.90, y=0.05)], "a": []})[0]
    assert inside["h"][20]["box"] == 1
    assert outside_x["h"][20]["box"] == 0      # outside the 16.5m line
    assert wide_y["h"][20]["box"] == 0         # inside the line but out by the touchline


def test_history_starts_where_the_engine_records():
    series, goals = reconstruct.build({"h": [shot(10, "h")], "a": []})
    hist = reconstruct.history_to(series, goals, "h", 45)
    start = config.CHECKPOINTS[0] - config.WINDOW - config.RECORD_LEAD
    assert hist[0].minute == start and hist[-1].minute == 45
    # a complete 30-minute window base must exist at the first checkpoint
    assert any(s.minute <= config.CHECKPOINTS[0] - config.WINDOW for s in hist)


# --- gating and settlement --------------------------------------------------
def test_favourite_band_matches_the_live_gate():
    """Band widened to 1.30-3.00 on 2026-08-23: a side quoted 2.99 pre-match
    that is dominating in play is still the thesis."""
    assert replay.favourite(1.80, 4.00) == ("h", 1.80)
    assert replay.favourite(4.00, 2.00) == ("a", 2.00)
    assert replay.favourite(1.20, 8.00) is None      # too short
    assert replay.favourite(2.99, 4.50) == ("h", 2.99)   # inside the wider band
    assert replay.favourite(3.20, 3.40) is None      # both beyond MAX_ODDS


def test_settlement_by_side():
    # level -> backed to win outright
    assert replay.settle("level", "h", 2, 1) is True
    assert replay.settle("level", "h", 1, 1) is False
    # behind -> backed the double chance, so a draw settles as a win
    assert replay.settle("behind", "h", 1, 1) is True
    assert replay.settle("behind", "h", 2, 1) is True
    assert replay.settle("behind", "h", 0, 1) is False
    # away favourite reads the scoreline the other way round
    assert replay.settle("level", "a", 1, 2) is True
    assert replay.settle("behind", "a", 1, 1) is True


def test_leading_checkpoints_are_excluded():
    """The favourite going ahead must stop producing rows - the strategy only
    backs a favourite that is failing to win."""
    fx = {"match_id": "x", "date": "2023-01-01", "home": "H", "away": "A",
          "goals_h": 3, "goals_a": 0, "odds_h": 1.80, "odds_a": 4.00}
    shots = {"h": [shot(5, "h", "Goal"), shot(6, "h", "Goal"), shot(7, "h", "Goal")],
             "a": []}
    assert replay.replay_match(fx, shots) == []
