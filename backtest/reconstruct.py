"""Shot events -> the per-minute snapshot series the live rule engine expects.

The monitor sees cumulative team statistics from API-Football once a minute.
Understat gives individual shots with a minute stamp, so the same series can be
rebuilt exactly: accumulate shots into per-minute totals and hand `rules` the
identical `Snapshot` objects the live engine records.

METRIC DEFINITIONS (mapping Understat -> the feed's four metrics)
  xg     sum of shot xG.
  shots  every shot event.
  sot    on target = Goal + SavedShot. BlockedShot is NOT on target (blocked by
         an outfield player), which matches the feed's "Shots on Goal".
  box    shot inside the penalty area, from the normalised X/Y coordinates.

  These are close to, not identical with, the feed's Opta-style definitions -
  `box` especially, which is derived from coordinates rather than reported. The
  backtest measures the RULE, and any residual definitional drift applies
  equally to both teams, so dominance ratios are largely unaffected.

KNOWN LIMITATION
  Understat carries only shots. The live feed's stats can lag or go missing,
  and xG is absent in some competitions; here every metric is always present
  and exact. So a replay sees cleaner data than the monitor does live, and will
  find somewhat MORE signals than the live system would. Treat replayed signal
  counts as an upper bound.
"""
from shotdominance import config, rules

MAX_MIN = 130

# Penalty area on a 105x68 pitch, in Understat's normalised coordinates: 16.5m
# from the goal line, 40.32m wide and centred.
BOX_X = 1.0 - 16.5 / 105.0
BOX_Y_LO = 0.5 - (40.32 / 2.0) / 68.0
BOX_Y_HI = 0.5 + (40.32 / 2.0) / 68.0

ON_TARGET = {"Goal", "SavedShot"}


def _in_box(shot):
    try:
        x, y = float(shot["X"]), float(shot["Y"])
    except (KeyError, TypeError, ValueError):
        return False
    return x >= BOX_X and BOX_Y_LO <= y <= BOX_Y_HI


def build(shots):
    """-> (series, goals) both keyed 'h'/'a'.

    series[side][m] is the cumulative metric dict for that side at minute m.
    goals[side][m]  is that side's score at minute m.

    An OwnGoal is recorded by Understat against the team that took the shot,
    but it is a goal FOR the opponent - credited accordingly here. Its xG and
    shot counts stay with the shooting team, as the feed would report them.
    """
    per = {s: [dict.fromkeys(config.KEYS, 0.0) for _ in range(MAX_MIN + 1)]
           for s in ("h", "a")}
    gl = {s: [0] * (MAX_MIN + 1) for s in ("h", "a")}

    for side in ("h", "a"):
        other = "a" if side == "h" else "h"
        for sh in shots.get(side) or []:
            m = min(int(sh["minute"]), MAX_MIN)
            bucket = per[side][m]
            bucket["shots"] += 1
            try:
                bucket["xg"] += float(sh["xG"])
            except (TypeError, ValueError):
                pass
            if sh["result"] in ON_TARGET:
                bucket["sot"] += 1
            if _in_box(sh):
                bucket["box"] += 1
            if sh["result"] == "Goal":
                gl[side][m] += 1
            elif sh["result"] == "OwnGoal":
                gl[other][m] += 1

    for side in ("h", "a"):
        run = dict.fromkeys(config.KEYS, 0.0)
        g = 0
        for m in range(MAX_MIN + 1):
            for k in config.KEYS:
                run[k] += per[side][m][k]
            per[side][m] = dict(run)
            g += gl[side][m]
            gl[side][m] = g
    return per, gl


def final_score(series_goals):
    return series_goals["h"][MAX_MIN], series_goals["a"][MAX_MIN]


def history_to(series, goals, fav_side, upto):
    """The snapshot history the live monitor would hold at `upto`.

    Recording starts where the engine starts it, so the momentum window has the
    same base it would have live (see RECORD_LEAD).
    """
    opp_side = "a" if fav_side == "h" else "h"
    start = config.CHECKPOINTS[0] - config.WINDOW - config.RECORD_LEAD
    out = []
    for m in range(start, min(upto, MAX_MIN) + 1):
        out.append(rules.Snapshot(m, dict(series[fav_side][m]),
                                  dict(series[opp_side][m]), goals[fav_side][m]))
    return out
