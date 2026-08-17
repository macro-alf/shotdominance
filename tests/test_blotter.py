"""The blotter must never lose a settled bet.

It is the only record that can turn the modelled edge into a measured one, and
a betting record that silently drops losers reports a flattering lie.
"""
from shotdominance import blotter

ROW = {"placed_at": "2026-08-15 17:36:28", "fixture_id": "1563088",
       "competition": "Championship", "match": "Norwich 0-0 West Brom",
       "minute": 71, "back": "Norwich", "side": "home", "market": "win",
       "score_at_bet": "0-0", "conviction": 60.0, "alert_price": 2.4,
       "stake": 781.0, "price_taken": 2.6, "final_score": "1-2",
       "status": "lost", "pnl": -781.0}


def test_write_preserves_rows_missing_from_memory(tmp_path):
    """Regression for 2026-08-16: a wiped state3.json left the monitor with an
    empty bet list and the next write deleted a settled loser from the file."""
    p = str(tmp_path / "blotter.csv")
    blotter.write(p, [ROW])
    blotter.write(p, [])                      # memory lost - disk must survive
    rows = blotter.read(p)
    assert len(rows) == 1 and rows[0]["match"] == "Norwich 0-0 West Brom"
    assert rows[0]["pnl"] == "-781.0"         # the LOSS is still there


def test_in_memory_bet_updates_its_row_on_settlement(tmp_path):
    p = str(tmp_path / "blotter.csv")
    open_bet = dict(ROW, final_score="", status="open", pnl="")
    blotter.write(p, [open_bet])
    blotter.write(p, [ROW])                   # same key, now settled
    rows = blotter.read(p)
    assert len(rows) == 1 and rows[0]["status"] == "lost"


def test_new_bets_append_without_touching_history(tmp_path):
    p = str(tmp_path / "blotter.csv")
    blotter.write(p, [ROW])
    later = dict(ROW, placed_at="2026-08-16 15:36:09", fixture_id="1548992",
                 match="FC Nordsjaelland 0-0 Silkeborg", status="won", pnl=1366.49)
    blotter.write(p, [later])
    rows = blotter.read(p)
    assert len(rows) == 2
    assert [r["status"] for r in rows] == ["lost", "won"]   # ordered by placed_at
