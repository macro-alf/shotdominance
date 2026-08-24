"""The 2026-08-24 fixes, each pinned to the signal that exposed it.

  PSG    - the bar must reflect the GOAL DEFICIT, not just goals scored.
  Milan  - 2 of 4 on both sides is the bare minimum twice over, not evidence.
  Verona - momentum alone with 1 of 4 cumulative is lopsided, not evidence.
"""
from shotdominance import config, rules


# --- PSG: the bar is what the BET costs, in goals ---------------------------
def test_two_goals_down_needs_two_goals_worth_of_evidence():
    """Rennes 2-0 PSG: the double chance only cashes on a draw, so PSG had to
    score TWICE. The bar was set at 1x because they had scored nothing."""
    assert rules.goals_needed(0, 2) == 2
    at_0_2, _ = rules.thresholds(59, fav_goals=0, opp_goals=2)
    at_0_1, _ = rules.thresholds(59, fav_goals=0, opp_goals=1)
    assert at_0_2["shots"] == 2 * at_0_1["shots"]


def test_deficit_and_scored_goals_both_count():
    cases = {(0, 0): 1, (1, 1): 2, (2, 2): 3,     # level: one more than scored
             (0, 1): 1, (1, 2): 2, (2, 3): 3,     # one behind: reach their total
             (0, 2): 2, (1, 3): 3, (0, 3): 3}     # two or three behind
    for (f, o), want in cases.items():
        assert rules.goals_needed(f, o) == want, "%d-%d" % (f, o)


def test_psg_row_would_no_longer_clear_the_bar():
    """PSG at 59' had 14 shots against a bar of 11.6 built for one goal. The
    two-goal bar is 23.2, which 14 does not reach."""
    vol, _ = rules.thresholds(59, fav_goals=0, opp_goals=2)
    assert 14 < vol["shots"]


# --- Milan / Verona: one side strong, the other adequate --------------------
def _ev(vol_met, mom_met):
    """Build an evaluation with exactly the requested met-counts by choosing
    how many metrics clear their bar on each side."""
    keys = list(config.KEYS)
    fav = {k: 0.0 for k in keys}
    opp = {k: 0.0 for k in keys}
    base_f = {k: 0.0 for k in keys}
    base_o = {k: 0.0 for k in keys}
    vol_th, mom_th = rules.thresholds(60, fav_goals=0, opp_goals=0)
    for i, k in enumerate(keys):
        cum = vol_th[k] * 1.5 if i < vol_met else 0.0
        win = mom_th[k] * 1.5 if i < mom_met else 0.0
        # cumulative must be at least the window gain, so build from the window
        fav[k] = max(cum, win)
        base_f[k] = fav[k] - win
    hist = {"m": [rules.Snapshot(30, base_f, base_o, 0)]}
    return rules.evaluate(hist, "m", 60, fav, opp, 0, 0)


def test_two_and_two_is_not_enough():
    """Torino 0-0 Milan: vol 2/4, mom 2/4, conviction 63."""
    ev = _ev(2, 2)
    assert ev.vol_met == 2 and ev.mom_met == 2
    assert not ev.ok and "need 3 on one" in ev.basis


def test_strong_on_one_side_and_adequate_on_the_other_fires():
    ev = _ev(3, 2)
    assert ev.vol_met == 3 and ev.mom_met == 2 and ev.ok


def test_lopsided_is_blocked_whichever_side_is_thin():
    """Verona was 1 of 4 cumulative with 3 of 4 momentum. The mirror image -
    strong cumulative, no momentum - is equally thin and equally blocked."""
    for v, m in ((1, 3), (3, 1), (0, 4), (4, 0)):
        ev = _ev(v, m)
        assert not ev.ok, "vol %d mom %d should be blocked" % (v, m)
