"""The blocked-signal ledger must be able to answer one question honestly:
did the refused bets win MORE OFTEN than the refused price implied?

If it drops rows, collapses distinct checkpoints, or grades a double chance as
an outright, the answer it gives is worse than no answer - it would be used to
retune the gate that produced it.
"""
from shotdominance import config, ledger

CTX = {"league": "Süper Lig", "label": "Galatasaray 0-0 Kocaelispor",
       "minute": 72, "state": "level", "side": "home", "market": "win",
       "fav": "Galatasaray", "score": "0-0", "conv": 79.0, "vol_met": 4,
       "mom_met": 4, "n_present": 4, "pm": 1.22, "price": 1.83, "need": 2.66,
       "winp": 0.46}


def _row(**over):
    r = ledger.new_block("1550119", 70, CTX, "price")
    r.update(over)
    return r


def test_a_block_records_the_price_refused_and_the_price_demanded():
    r = _row()
    assert r["live_price"] == "1.83" and r["need"] == "2.66"
    assert r["prematch_price"] == "1.22" and r["conviction"] == "79"
    assert r["blocked_by"] == "price" and r["status"] == "open"


def test_repeated_evaluations_of_one_checkpoint_collapse_to_one_row(tmp_path):
    """At cp45 the half-time clock freeze holds a grace window open for dozens
    of polls. Each must update one row, not append a new one."""
    p = str(tmp_path / "blocked.csv")
    rows = [_row(seen_at="2026-09-13 20:0%d:00" % i) for i in range(6)]
    for i in range(1, 7):
        ledger.write(p, rows[:i])
    assert len(ledger.read(p)) == 1


def test_distinct_checkpoints_on_one_fixture_are_kept_apart(tmp_path):
    p = str(tmp_path / "blocked.csv")
    ledger.write(p, [_row(checkpoint=cp) for cp in (45, 50, 55, 60, 65, 70)])
    assert len(ledger.read(p)) == 6


def test_write_never_drops_a_row_missing_from_memory(tmp_path):
    """Same discipline as the blotter: a record that quietly loses rows is a
    flattering lie, and this one would be used to retune the gate."""
    p = str(tmp_path / "blocked.csv")
    ledger.write(p, [_row(checkpoint=45, status="lost", pnl_at_quote=-1.0)])
    ledger.write(p, [])
    assert len(ledger.read(p)) == 1
    ledger.write(p, [_row(checkpoint=50)])
    assert len(ledger.read(p)) == 2


def test_an_outright_block_is_graded_on_the_favourite_winning():
    won = _row()
    ledger.settle_block(won, "Galatasaray", 1, 0)
    assert won["status"] == "won"
    assert abs(won["pnl_at_quote"] - 0.83 * (1 - config.COMMISSION)) < 1e-6
    lost = _row()
    ledger.settle_block(lost, "Galatasaray", 0, 0)      # a draw loses outright
    assert lost["status"] == "lost" and lost["pnl_at_quote"] == -1.0


def test_a_double_chance_block_is_graded_on_avoiding_defeat():
    r = _row(market="1X", state="behind")
    ledger.settle_block(r, "Galatasaray", 1, 1)
    assert r["status"] == "won", "a draw settles the double chance"


def test_the_away_favourite_is_graded_from_side_not_the_team_name():
    r = _row(side="away", back="Kocaelispor")
    ledger.settle_block(r, "Galatasaray", 0, 2)
    assert r["status"] == "won"


def test_a_block_with_no_quote_is_graded_but_earns_no_counterfactual_pnl():
    """The half-time blind spot. There was no price to take, so there is no
    return to compute - but the RESULT is still worth keeping."""
    r = _row(live_price="")
    ledger.settle_block(r, "Galatasaray", 1, 0)
    assert r["status"] == "won" and r["pnl_at_quote"] == ""


def test_summing_pnl_at_quote_measures_whether_the_gate_pays():
    """Galatasaray 2026-09-13: refused six times at ~1.8, then won 1-0. One
    winner does not vindicate ignoring the gate - at 1.83 you need ~55% - but
    the ledger must at least add up."""
    rows = [_row(checkpoint=cp, live_price="1.83") for cp in (45, 50, 55)]
    for r in rows:
        ledger.settle_block(r, "Galatasaray", 1, 0)
    total = sum(float(r["pnl_at_quote"]) for r in rows)
    assert total > 0, "three wins at 1.83 must show a positive counterfactual"
