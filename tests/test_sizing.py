"""Sizing tests: the target-win base, the conviction multiplier, and the Kelly
ceiling / exposure clamps from HANDOVER.md.
"""
from shotdominance import config, sizing


def test_target_win_base():
    # base stake targets TARGET_WIN profit: base*(price-1) == TARGET_WIN
    for price in (1.80, 2.50, 4.00):
        s = sizing.size(price, conv=config.CONV_MID)
        assert abs(s["base"] * (price - 1.0) - config.TARGET_WIN) < 1e-6


def test_conviction_multiplier_endpoints():
    assert abs(sizing.conviction_multiplier(config.CONV_MID) - 1.0) < 1e-9
    assert abs(sizing.conviction_multiplier(config.CONV_TOP) - config.MULT_MAX) < 1e-9
    # clamped both ends
    assert sizing.conviction_multiplier(0) == config.MULT_MIN
    assert sizing.conviction_multiplier(200) == config.MULT_MAX


def test_stake_never_exceeds_per_bet_cap():
    cap = config.MAX_STAKE_PCT * config.BANKROLL
    for price in (1.75, 2.00, 3.00, 4.00):
        stake, p, f = sizing.stake_for(price)
        assert stake <= cap + 1e-9
        assert 0.0 <= p <= 0.99


def test_kelly_is_a_ceiling():
    # very high conviction wants a large stake; it must still be bounded by the
    # Kelly stake when Kelly is the smaller of the two.
    s = sizing.size(2.00, conv=100)
    assert s["stake"] <= s["kelly"] + 1e-9
    if s["kelly"] < s["want"]:
        assert s["bound"] == "Kelly"


def test_exposure_room_clamps_stake():
    # already near the total exposure cap -> new stake is squeezed to the room
    room = config.MAX_TOTAL_PCT * config.BANKROLL
    s = sizing.size(2.50, conv=80, open_total=room - 100.0)
    assert s["stake"] <= 100.0 + 1e-9
