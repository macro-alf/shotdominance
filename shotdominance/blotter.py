"""The blotter: the CSV record of self-reported bets and their settlement.

Nothing here places a bet. record_bet builds a row from the alert context you
acknowledged; settle closes it out once the fixture leaves the live board and
reports a finished status. The blotter is the ONLY instrument that can turn the
modelled edge into a measured one - it needs a few hundred settled bets before
it says anything that is not noise.
"""
import csv
import time

from . import config

COLS = ["placed_at", "fixture_id", "competition", "match", "minute", "back",
        "side", "market", "score_at_bet", "conviction", "alert_price", "stake",
        "price_taken", "final_score", "status", "pnl"]


def write(path, bets):
    try:
        with open(path, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=COLS)
            w.writeheader()
            for b in bets:
                w.writerow({k: b.get(k, "") for k in COLS})
    except Exception as e:
        print("  ! blotter write failed:", e, flush=True)


def new_bet(fid, ctx, stake, price):
    """Build a blotter row (status 'open') from the acknowledged alert context.

    `market` records what was actually backed: 'win' (favourite to win) or the
    double chance '1X'/'X2' (favourite win or draw), which settle_bet needs to
    grade the bet correctly."""
    return dict(placed_at=time.strftime("%Y-%m-%d %H:%M:%S"), fixture_id=fid,
                competition=ctx.get("league", ""), match=ctx.get("label", ""),
                minute=ctx.get("minute", ""), back=ctx.get("fav", ""),
                side=ctx.get("side", ""), market=ctx.get("market", "win"),
                score_at_bet=ctx.get("score", ""), conviction=ctx.get("conv", ""),
                alert_price=ctx.get("price", ""), stake=stake, price_taken=price,
                final_score="", status="open", pnl="")


def settle_bet(bet, home_name, hs, as_):
    """Mutate one open bet to won/lost with its P&L, recording the final score.
    Returns True if settled.

    Which side the favourite is on is taken from the bet's stored `side`
    (home/away) - robust to team-name variations - falling back to a name match
    only for legacy rows. A 'win' bet needs the favourite to win outright; a
    double-chance bet ('1X'/'X2') needs it merely to avoid defeat (a draw wins)."""
    side = bet.get("side")
    fav_is_home = (side == "home") if side in ("home", "away") \
        else (bet["back"] == home_name)
    if fav_is_home:
        won_outright, not_lost = hs > as_, hs >= as_
    else:
        won_outright, not_lost = as_ > hs, as_ >= hs
    is_dc = bet.get("market", "win") != "win"
    won = not_lost if is_dc else won_outright
    stake, price = float(bet["stake"]), float(bet["price_taken"])
    bet["final_score"] = "%d-%d" % (hs, as_)
    bet["pnl"] = round(
        stake * (price - 1) * (1 - config.COMMISSION) if won else -stake, 2)
    bet["status"] = "won" if won else "lost"
    return True
