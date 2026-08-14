"""Tests for the double-chance market change: when the favourite is behind, the
strategy trades win-or-draw (1X / X2), taken live or derived from the
opponent's win odds, and settled accordingly.
"""
from shotdominance import apifootball, blotter


# --- double-chance key normalisation ----------------------------------------
def test_dc_key_variants():
    assert apifootball.dc_key("Home/Draw") == "1X"
    assert apifootball.dc_key("1X") == "1X"
    assert apifootball.dc_key("Draw/Away") == "X2"
    assert apifootball.dc_key("X2") == "X2"
    assert apifootball.dc_key("Home/Away") == "12"
    assert apifootball.dc_key("12") == "12"


# --- live_prices captures the double-chance market ---------------------------
class _StubApi:
    def __init__(self, rows):
        self._rows = rows

    def get(self, path, **p):
        return self._rows if path == "/odds/live" else []


def test_live_prices_captures_dc():
    rows = [{"fixture": {"id": 5}, "status": {}, "odds": [
        {"name": "Match Winner", "values": [
            {"value": "Home", "odd": "2.1"}, {"value": "Away", "odd": "3.4"},
            {"value": "Draw", "odd": "3.1"}]},
        {"name": "Double Chance", "values": [
            {"value": "Home/Draw", "odd": "1.30"},
            {"value": "Draw/Away", "odd": "1.55"}]}]}]
    prices = apifootball.live_prices(_StubApi(rows))
    assert prices["5"]["Home"] == 2.1
    assert prices["5"]["1X"] == 1.30
    assert prices["5"]["X2"] == 1.55


# --- price selection --------------------------------------------------------
def test_level_favourite_uses_win_odds():
    fx = {"Home": 2.4, "Away": 3.0, "Draw": 3.2}
    r = apifootball.signal_price(fx, "home", behind=False)
    assert r == {"price": 2.4, "market": "win", "kind": "win", "derived": False}


def test_behind_prefers_live_double_chance():
    fx = {"Home": 3.5, "Away": 2.1, "1X": 1.9}
    r = apifootball.signal_price(fx, "home", behind=True)
    assert r["price"] == 1.9 and r["market"] == "1X"
    assert r["kind"] == "dc" and r["derived"] is False


def test_behind_derives_dc_from_underdog_odds():
    # home favourite behind, no live DC; underdog (away) win odds = 1.5
    # P(underdog)=1/1.5=0.667 -> P(win or draw)=0.333 -> dc odds = 3.0
    fx = {"Home": 6.0, "Away": 1.5}
    r = apifootball.signal_price(fx, "home", behind=True)
    assert r["market"] == "1X" and r["kind"] == "dc" and r["derived"] is True
    assert abs(r["price"] - 3.0) < 1e-9


def test_away_favourite_behind_uses_x2_and_home_underdog():
    fx = {"Home": 1.5, "Away": 6.0}          # away fav behind; underdog=home=1.5
    r = apifootball.signal_price(fx, "away", behind=True)
    assert r["market"] == "X2"
    assert abs(r["price"] - 3.0) < 1e-9


def test_behind_with_no_prices_yields_none():
    r = apifootball.signal_price({}, "home", behind=True)
    assert r["price"] is None and r["kind"] == "dc"


# --- settlement -------------------------------------------------------------
def _bet(back, market, price=2.0, stake=100.0):
    return dict(back=back, market=market, stake=stake, price_taken=price,
                status="open", pnl="")


def test_double_chance_settles_draw_as_win():
    b = _bet("Ajax", "1X")               # home favourite, win-or-draw
    blotter.settle_bet(b, "Ajax", 1, 1)  # a draw
    assert b["status"] == "won" and b["pnl"] > 0


def test_double_chance_loses_only_on_defeat():
    b = _bet("Ajax", "1X")
    blotter.settle_bet(b, "Ajax", 0, 1)  # favourite loses
    assert b["status"] == "lost" and b["pnl"] < 0


def test_win_market_draw_is_a_loss():
    b = _bet("Ajax", "win")
    blotter.settle_bet(b, "Ajax", 1, 1)  # a draw does not win the outright bet
    assert b["status"] == "lost"


def test_away_double_chance_settles():
    b = _bet("PEC", "X2")                 # PEC are away, backed win-or-draw
    blotter.settle_bet(b, "Ajax", 2, 2)   # home_name=Ajax, 2-2 draw
    assert b["status"] == "won"
