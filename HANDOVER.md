# In-play football monitor — handover

Read this first; the [README](README.md) covers setup and layout. This document
is the rule specification and the honest account of what is and isn't known.

## What it does

Watches live football via API-Football. When a pre-match favourite is failing to
win but dominating the shot count, it sends a Telegram alert with a stake
suggestion. **It never places bets.** It alerts, and records bets you tell it you
placed.

## The rule set (current, as of 2026-08-13)

Eligibility
- Competition in the 24-league list (`config.LEAGUES`)
- Pre-match favourite decimal odds **1.30–2.25**
- Favourite **not currently winning**
- Checkpoints at minutes **45, 50, 55, 60, 65, 70, 75** — each evaluated once

Metrics (4): `xg`, `shots` (total), `sot` (on target), `box` (shots inside box)

Baseline thresholds **at minute 45**: xG 0.70 | shots 10 | on target 3 | insidebox 5
Volume threshold at minute *t* scales linearly: `base * t / 45`
Momentum threshold is constant: `base * 30 / 45` (a 30-minute trailing window)

A metric counts as **realised** only if BOTH:
1. value ≥ its threshold, AND
2. opponent's value on that same metric ≤ **50%** of ours (`DOM_RATIO`)

The requirement is **≥2 of the metrics that have data**, not always "of 4": when
xG is absent for a match (common — see known-issue #1) the rule becomes **2 of
3** and the console/alert print the true denominator (`vol=2/3`).

Signal logic
- **Favourite has not scored** (0-0, 0-1, …): need ≥2 on volume **AND**
  ≥2 on momentum. An incomplete momentum window (`~`) blocks the signal.
- **Favourite has scored and is level/behind** (1-1, 2-2, 1-2): **EITHER**
  ≥2 of 4 on momentum, **OR** ≥2 of 4 on cumulative-from-kickoff measured
  against a `(fav_goals + 1)×` threshold. Note this is *looser* than the 0-0
  case — a known and deliberate consequence of "either/or".
- Price / market (depends on the scoreline):
  - **Favourite level** (0-0, 1-1, …): back it to **win**; the live
    favourite-to-win price must be **1.75–4.00**.
  - **Favourite behind** (0-1, 1-2, …): the tradeable market becomes the
    **double chance** — favourite win *or* draw (**1X** for a home favourite,
    **X2** for an away one). That double-chance price must be **1.75–4.00** (same
    band). Taken live from the feed when offered, otherwise **derived** by
    combining the two winning legs: `dc = 1 / (1/fav_win + 1/draw)` (1X from
    Home+Draw, X2 from Away+Draw). This carries the same 1x2 margin as the
    outright prices, so it reproduces the feed's own live DC to ~1% (verified
    against `/odds/live`); it is flagged "derived odds" in the alert. If the
    Draw price is absent the condition is skipped rather than guessed.
  - If no usable live price is available the condition is **skipped**, not
    failed, and the alert still fires. Live odds flicker in and out
    (blocked/suspended); the **last live price for a fixture is carried forward
    for up to `PRICE_CARRY_TTL` (180s)** so a momentary gap at a checkpoint does
    not drop the price.
  - Sizing uses whichever price applies, and the blotter records the `market`
    (`win` / `1X` / `X2`) so settlement grades it correctly: a **win** bet needs
    an outright win, a **double chance** needs the favourite merely to avoid
    defeat (a draw settles it as a win).

Conviction score (0–100): `50 × (0.6·mean + 0.4·min)` of the ratio-to-threshold
vector, capped at 2×, combined 0.55 volume / 0.30 momentum / 0.15 dominance.
50 = everything exactly at threshold. 100 = everything at double.

Firing policy (conviction gate): an eligible signal fires only if conviction is
**≥ `CONV_FIRE_MIN` (50)**, and a live signal **re-fires only when its conviction
exceeds the highest already alerted** for that fixture — so a deteriorating
situation is not repeated. Alerts still stop entirely once you reply "bet done".

Sizing: base = `1000 / (price − 1)` (target win €1,000), multiplied by
`1.0 + (MULT_MAX−1)·(conv−50)/(85−50)` clamped to [0.5, 2.0], then capped by
0.65-Kelly and a 10%-of-bankroll per-bet cap. Bankroll €20,000, commission 3%.

Alerts repeat at every checkpoint while the signal holds, until you reply
**"bet done" as a reply to that specific Telegram message**. The bot then asks
for stake and price, writes `blotter.csv`, and settles at full time.

## Architecture

One package, one import direction — no monkeypatching. `engine.Monitor` owns all
cross-poll state and calls into the leaf modules; nothing calls back.

    monitor.py            entry point (--stats / --once / run)
      shotdominance.engine.Monitor        the poll loop + all mutable state
        shotdominance.apifootball         API client, odds, stats, leagues (empirical)
        shotdominance.rules               pure decision logic (this spec)
        shotdominance.sizing              Kelly ceiling + conviction multiplier
        shotdominance.telegram            two-way Telegram
        shotdominance.blotter             CSV bet record + settlement
        shotdominance.state               JSON persistence
        shotdominance.config              every tunable, env-overridable

    daily.py    supervisor: schedule, launch monitor as a child, tee to logs/,
                detect end of day, run endday.py, sleep the PC
    endday.py   end-of-day report + pasteable digest + Telegram summary
    review.py   log analyser — recomputes WHY each metric failed

The console log format is byte-compatible with the old build so `review.py` keeps
working, with one addition: the pre-match price (`pm=`) is now printed, so the
effect of the 1.30–2.25 gate is measurable from the logs.

### Migration notes (from the seven-file chain)

- The old ordering `monitor2 → run4 → run5 → run6 → run7/monitor3`, with
  `monitor3` rebinding `run5._orig_poll`, is gone. The pacing/backoff that run5
  provided now lives inside `apifootball.ApiClient.get`.
- The rules were rebuilt from this spec. The API adapter (endpoint paths, stat
  type matching, FT-market filtering, favourite resolution, Czech aliasing) was
  carried across unchanged.

## Known issues

Status against the rebuild:

1. **xG presence unconfirmed.** xG was absent on every poll of 2026-08-12
   (`[xG NOT SEEN YET]`). Unresolved — it is a feed question, not a code one.
   Run `python monitor.py --stats` during a major-league match to settle it.
   Until then treat the rule as effectively 3-condition. *(A missing xG is
   already handled safely: it can never pass and never falsely fail.)*
2. **Missing stat defaulting.** ~~`parse_stats` defaulted a missing stat to 0.~~
   **Fixed** — all four metrics default to `None`, so "no data" is distinct from
   "zero", everywhere.
3. **Encoding corruption.** ~~A `Get-Content | Out-File` round-trip on Windows
   PowerShell 5.1 mangled accented league names and silently dropped two
   competitions.~~ **Mitigated** — `config.py` is UTF-8, and `PINNED_IDS` (Segunda
   División 141, Süper Lig 203) is a hard fallback if name matching ever fails.
   Prefer editing config in a UTF-8-aware editor.
4. **Live price mapping is unverified.** `live_prices()` merges every whitelisted
   full-time market into one dict per fixture, last write wins. One observed
   price (Ajax 1.61 at 76' from 0-0) was implausible for the favourite and may
   have been the draw. **Still open** — verify against a raw `/odds/live` dump
   before trusting the price band.
5. **Wake timer unproven.** The 08:00 task has fired via `StartWhenAvailable`
   rather than an actual wake. **Still open** — check Power-Troubleshooter events.

## What is NOT established

- **There is no measured edge.** Everything about expected value comes from a
  Monte Carlo simulation, and it bounds the edge between **+22.3%** (if the
  market prices no shot dominance at all) and **−0.2%** (if it prices it as well
  as you can observe it). Nobody knows where reality sits. The `blotter.csv` is
  the first instrument capable of answering that, and it needs a few hundred
  settled bets before it says anything that is not noise.
- Statistical power: detecting a true +10% ROI at 95% confidence needs ~1,900
  bets. A single season of P&L carries a ±30% interval.
- An optimisation pass over the rule parameters selected a **placebo variable**
  (home/away, which has no causal effect) in 10 of the top 15 configurations.
  In-sample +119% ROI became +39.5% out of sample. Do not tune on backtests.
- The simulator behind the edge curve models the OLD rules (shots + on target,
  no xG, no dominance test, 3 checkpoints). It is valid for comparing prices
  against each other, not for validating the current gates.
