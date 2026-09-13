"""Sizing tests: the target-win base, the conviction multiplier, and the Kelly
ceiling / exposure clamps from HANDOVER.md.
"""
from shotdominance import config, sizing


def test_stake_is_flat_in_price():
    """Changed 2026-09-07: the stake is a conviction ladder, flat in price.

    Alf's requirement: a longer price must not shrink the bet at the same
    conviction. Kelly did exactly that (f = EV/b), so it no longer sets the
    stake -- it is computed and reported only.
    """
    for conv in (70, 80, 100):
        stakes = [sizing.size(price, conv)["stake"]
                  for price in (1.75, 2.00, 2.50, 3.00, 4.00)]
        assert max(stakes) - min(stakes) < 1e-6, (conv, stakes)


def test_conviction_ladder_endpoints():
    # the firing floor earns STAKE_AT_FLOOR, full conviction earns STAKE_AT_TOP
    assert abs(sizing.size(2.00, config.CONV_FIRE_MIN)["stake"]
               - config.STAKE_AT_FLOOR) < 1e-6
    assert abs(sizing.size(2.00, config.CONV_STAKE_TOP)["stake"]
               - config.STAKE_AT_TOP) < 1e-6
    # and it rises monotonically between them
    prev = -1.0
    for conv in range(int(config.CONV_FIRE_MIN), int(config.CONV_STAKE_TOP) + 1):
        cur = sizing.size(2.00, conv)["stake"]
        assert cur >= prev - 1e-9
        prev = cur


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


def test_kelly_is_reported_but_no_longer_binds():
    # Kelly is still computed for the alert and for later comparison, but it
    # does not cap the stake any more.
    s = sizing.size(2.00, conv=100)
    assert "kelly" in s and "p" in s and "f" in s
    assert s["bound"] in ("conviction ladder", "exposure cap")


def test_exposure_room_clamps_stake():
    # already near the total exposure cap -> new stake is squeezed to the room
    room = config.MAX_TOTAL_PCT * config.BANKROLL
    s = sizing.size(2.50, conv=80, open_total=room - 100.0)
    assert s["stake"] <= 100.0 + 1e-9
