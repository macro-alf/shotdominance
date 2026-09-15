"""The blocked-signal ledger: what the gates REFUSED, and what happened next.

The blotter records bets that were placed. This records the counterfactual - a
checkpoint where the evidence rule passed but no alert fired, together with the
price that was quoted, the price the model demanded, and (once the fixture
finishes) whether the bet we declined would in fact have won.

Why it exists. Since the minimum-price gate went live on 2026-09-13 it, not
conviction, has been the binding constraint: 45 refusals on its first afternoon
against 2 alerts. Nothing recorded them, so the only evidence about whether the
gate earns its keep was anecdote - Galatasaray 0-0 Kocaelispor refused six times
at 1.83 and winning 1-0, Inter 2-2 Udinese refused at 1.44. One outcome cannot
distinguish a 46% process from a 56% one; a few hundred can.

The question this table is built to answer is NOT "did the blocked bets win".
It is "did they win MORE OFTEN than the price we refused implied". A block at
1.83 that wins 50% of the time was a good block (break-even there is ~55%); a
block at 3.50 that wins 40% was a bad one. `pnl_at_quote` is per unit stake, so
summing it over the settled rows gives the P&L of the strategy of ignoring the
gate - if that number is reliably negative, the gate is paying for itself.

Nothing here places or suggests a bet. It is a measurement instrument.
"""
import csv
import time

from . import config

COLS = ["seen_at", "day", "fixture_id", "competition", "match", "minute",
        "checkpoint", "state", "side", "market", "back", "score_at_block",
        "conviction", "vol_met", "mom_met", "n_present", "prematch_price",
        "live_price", "need", "winp", "blocked_by", "final_score", "status",
        "pnl_at_quote"]


def _key(row):
    """Identity of a block on disk: one fixture, one checkpoint, one day.

    Keyed on the checkpoint rather than the timestamp so that the repeated
    evaluations inside an open grace window collapse to a single row that keeps
    being updated with the latest reading, instead of writing one row per poll.
    That matters at cp45, where the half-time clock freeze can hold a window
    open for dozens of polls.
    """
    return (str(row.get("day", "")), str(row.get("fixture_id", "")),
            str(row.get("checkpoint", "")))


def read(path):
    try:
        with open(path, newline="", encoding="utf-8") as fh:
            return [r for r in csv.DictReader(fh) if r.get("day")]
    except FileNotFoundError:
        return []
    except Exception as e:
        print("  ! ledger read failed:", e, flush=True)
        return []


def write(path, blocks):
    """Persist `blocks`, MERGING with whatever is already on disk.

    Same discipline as the blotter, for the same reason: a record that silently
    drops rows is worse than no record. Rows on disk are never deleted; an
    in-memory row replaces its match and everything else is preserved.
    """
    try:
        merged = {}
        for row in read(path):
            merged[_key(row)] = {k: row.get(k, "") for k in COLS}
        for b in blocks:
            merged[_key(b)] = {k: b.get(k, "") for k in COLS}
        with open(path, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=COLS)
            w.writeheader()
            for _k, row in sorted(merged.items()):
                w.writerow(row)
    except Exception as e:
        print("  ! ledger write failed:", e, flush=True)


def new_block(fid, cp, ctx, blocked_by):
    """Build a ledger row (status 'open') for a refused checkpoint.

    `blocked_by` is a short slug for the binding constraint - "price" when the
    minimum-price gate refused it, "conviction" when the floor did, "band" for
    the odds band, and combinations joined by '+'. The evidence rule is NOT a
    reason recorded here: rows are only written when the evidence rule passed,
    which is what makes the set small enough to be worth settling.
    """
    price = ctx.get("price")
    return dict(
        seen_at=time.strftime("%Y-%m-%d %H:%M:%S"),
        day=time.strftime("%Y-%m-%d"), fixture_id=fid,
        competition=ctx.get("league", ""), match=ctx.get("label", ""),
        minute=ctx.get("minute", ""), checkpoint=cp, state=ctx.get("state", ""),
        side=ctx.get("side", ""), market=ctx.get("market", "win"),
        back=ctx.get("fav", ""), score_at_block=ctx.get("score", ""),
        conviction=("%.0f" % ctx["conv"]) if ctx.get("conv") is not None else "",
        vol_met=ctx.get("vol_met", ""), mom_met=ctx.get("mom_met", ""),
        n_present=ctx.get("n_present", ""),
        prematch_price=("%.2f" % ctx["pm"]) if ctx.get("pm") else "",
        live_price=("%.2f" % price) if price else "",
        need=("%.2f" % ctx["need"]) if ctx.get("need") else "",
        winp=("%.3f" % ctx["winp"]) if ctx.get("winp") is not None else "",
        blocked_by=blocked_by, final_score="", status="open", pnl_at_quote="")


def settle_block(row, home_name, hs, as_):
    """Grade a refused checkpoint as if the bet HAD been taken at the quote.

    Graded exactly as blotter.settle_bet grades a real bet - outright for a
    'win' market, win-or-draw for a double chance - so the two tables are
    directly comparable. `pnl_at_quote` is per unit stake: summing it over
    settled rows gives what ignoring the gate would have returned.

    A row with no live price is settled for its RESULT but left with no P&L:
    there was no quote to take, so there is no counterfactual return to compute.
    Those rows are the half-time blind spot and should be read separately.
    """
    side = row.get("side")
    fav_is_home = (side == "home") if side in ("home", "away") \
        else (row.get("back") == home_name)
    if fav_is_home:
        won_outright, not_lost = hs > as_, hs >= as_
    else:
        won_outright, not_lost = as_ > hs, as_ >= hs
    is_dc = row.get("market", "win") != "win"
    won = not_lost if is_dc else won_outright
    row["final_score"] = "%d-%d" % (hs, as_)
    row["status"] = "won" if won else "lost"
    try:
        price = float(row.get("live_price") or 0)
    except ValueError:
        price = 0.0
    row["pnl_at_quote"] = (
        round((price - 1) * (1 - config.COMMISSION) if won else -1.0, 4)
        if price > 1 else "")
    return True
