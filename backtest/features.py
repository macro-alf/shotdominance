"""Extract the raw ingredients of every eligible checkpoint, once.

    python -m backtest.features --seasons 2020,2021,2022,2023 --out feat.csv

The engine reports counts ("2 of 4 metrics realised"). To ask which metric
carries the signal, or whether a short momentum window beats the 30-minute one,
the underlying per-metric numbers are needed. This writes them all out so the
search is filtering over a table rather than re-running the replay for every
candidate - which also keeps the search auditable: every candidate is a query
over one fixed dataset.

Columns per metric k in (xg, shots, sot, box):
    v_<k>       favourite cumulative
    o_<k>       opponent cumulative
    r_<k>       v/threshold at this minute (the volume ratio)
    d_<k>       opponent share o/v (dominance; lower is better)
    m30_<k>     favourite gain over the last 30 minutes
    md30_<k>    opponent share of that 30-minute gain
    m15_<k>     favourite gain over the last 15 minutes (a "recent surge" test
                the live rule does not currently look at)
    md15_<k>    opponent share of the 15-minute gain
"""
import argparse
import csv

from shotdominance import config, rules

from . import reconstruct, replay, sources

SHORT_WINDOW = 15


def _share(fav, opp):
    if fav is None or opp is None or fav <= 0:
        return None
    return opp / fav


def rows_for(fx, shots, season, league):
    fav = replay.favourite(fx["odds_h"], fx["odds_a"])
    if fav is None:
        return []
    fav_side, fav_price = fav
    opp_side = "a" if fav_side == "h" else "h"

    series, goals = reconstruct.build(shots)
    fh, fa = reconstruct.final_score(goals)
    if (fh, fa) != (fx["goals_h"], fx["goals_a"]):
        return []

    out = []
    best = 0.0
    for cp in config.CHECKPOINTS:
        fav_g, opp_g = goals[fav_side][cp], goals[opp_side][cp]
        if fav_g > opp_g:
            continue
        state = "level" if fav_g == opp_g else "behind"

        hist = reconstruct.history_to(series, goals, fav_side, cp)
        f_now, o_now = series[fav_side][cp], series[opp_side][cp]
        ev = rules.evaluate({fx["match_id"]: hist}, fx["match_id"], cp,
                            f_now, o_now, fav_g, opp_g)
        fired = bool(ev.ok and ev.conv >= config.CONV_FIRE_MIN and ev.conv > best)
        if fired:
            best = ev.conv

        vol_th, _mom_th = rules.thresholds(cp, fav_goals=fav_g, opp_goals=opp_g)
        r = {"match_id": fx["match_id"], "season": season, "league": league,
             "date": fx["date"], "minute": cp, "state": state,
             "fav_price": fav_price, "fav_goals": fav_g, "opp_goals": opp_g,
             "conv": ev.conv, "s_vol": ev.s_vol, "s_mom": ev.s_mom,
             "s_dom": ev.s_dom, "time_mult": ev.time_mult,
             "vol_met": ev.vol_met, "mom_met": ev.mom_met,
             "rule_ok": int(ev.ok), "fired": int(fired),
             "won": int(bool(replay.settle(state, fav_side, fh, fa)))}

        for k in config.KEYS:
            v, o = f_now[k], o_now[k]
            r["v_" + k] = round(v, 4)
            r["o_" + k] = round(o, 4)
            r["r_" + k] = round(v / vol_th[k], 4) if vol_th[k] > 0 else None
            r["d_" + k] = _share(v, o)
            for w, tag in ((config.WINDOW, "30"), (SHORT_WINDOW, "15")):
                base = max(cp - w, 0)
                mv = v - series[fav_side][base][k]
                mo = o - series[opp_side][base][k]
                r["m%s_%s" % (tag, k)] = round(mv, 4)
                r["md%s_%s" % (tag, k)] = _share(mv, mo)
        out.append(r)
    return out


def build(seasons, leagues):
    rows = []
    for season in seasons:
        for lg in leagues:
            matched, _ = sources.joined(lg, season)
            for fx in matched:
                try:
                    shots = sources.match_shots(fx["match_id"])
                except Exception:
                    continue
                rows.extend(rows_for(fx, shots, season, lg))
            print("  %s %s: %d rows" % (lg, season, len(rows)), flush=True)
    return rows


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--leagues", default=",".join(sources.LEAGUES))
    ap.add_argument("--seasons", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)

    rows = build([s.strip() for s in a.seasons.split(",") if s.strip()],
                 [x.strip() for x in a.leagues.split(",") if x.strip()])
    with open(a.out, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print("%d rows -> %s" % (len(rows), a.out))


if __name__ == "__main__":
    main()
