# In-play football monitor — handover

Read this first; the [README](README.md) covers setup and layout. This document
is the rule specification and the honest account of what is and isn't known.

## What it does

Watches live football via API-Football. When a pre-match favourite is failing to
win but dominating the shot count, it sends a Telegram alert with a stake
suggestion. **It never places bets.** It alerts, and records bets you tell it you
placed.

## The rule set (current, as of 2026-09-21)

Eligibility
- Competition in the 25-competition list (`config.LEAGUES`), all ids pinned in
  `config.PINNED_IDS`.
- Pre-match favourite decimal odds **1.01-3.00** (`MIN_ODDS`/`MAX_ODDS`). Note
  this gates the PRE-MATCH price only - there is no live ceiling, a known gap.
- Favourite **not currently winning**.
- Checkpoints at **45, 50, 55, 60, 65, 70, 75**, grace 4 minutes. `due_checkpoint`
  retires every reached-but-lower checkpoint, so only the latest can fire.

Metrics (4): `xg`, `shots`, `sot`, `box`. Live coverage is mostly THREE - 86% of
September rows carried 3 metrics, 6.9% carried 4, 2.2% carried 2.

Baseline thresholds at minute 45: xG 0.70 | shots 10 | sot 3 | box 5
- volume bar grows with `vol_scale(minute)` and is multiplied by
  `goals_needed = max(fav_goals+1, opp_goals)`;
- momentum bar scales with the window actually measured (30 min, floor 20).

A metric is **realised** only if value >= threshold AND opponent <= 50% of ours.

**How many metrics are demanded scales with how many exist** (`rule_thresholds`,
measured 2026-09-20 on 34,734 backtest rows against a 31.9% base):

    n=4   need 2, strong 3    5.7% pass, 45.7% win   <- the calibration
    n=3   need 2, strong 2    4.7% pass, 45.6% win   <- reproduces it
    n=2   need 1, strong 2    4.1% pass, 44.5% win
    n<=1  unreachable - too little to judge

Signal logic
- **Favourite has not scored**: >= need on volume AND on momentum.
- **Favourite has scored and is level/behind**: momentum OR cumulative (the
  volume bar already carries the goals_needed multiplier). Momentum-only was
  measured and REJECTED 2026-09-20 - see TODO.
- The STRONG gate then requires the better axis to reach `strong` and the other
  to reach `need`.
- An incomplete momentum window (`~`, `approx`) blocks the signal, and since
  2026-09-21 also **caps conviction below the firing floor** - with no window,
  `s_mom` is whole-match totals wearing a momentum label and 60% of the score is
  fabricated.

Conviction = **0.40 x volume + 0.60 x momentum**. Dominance carries zero weight
(measured 2026-09-20: it separated winners by +2.1pp and is already enforced
twice elsewhere). Floor to fire: **60**. Stake ladder 1000 at 60 -> 2000 at 100,
flat in price; Kelly is reported but not binding.

Price gate - the binding constraint in practice
- `min_price(state, minute, conv, pm)` = break-even on `COMMISSION` (3%),
  floored at **MIN_BACKABLE_ODDS 1.80**, with `EDGE_MARGIN` 0.
- P(win) is fitted on 2020-23 rule_ok rows with penalties stripped, refit
  2026-09-20 to the new conviction scale: level 0.6101/-0.009906, behind
  0.5978/-0.008342, +0.074 for conviction >= 70, capped at **0.75** (above that
  the model over-predicted by ~10pp).
- **Pre-match price is an input** and matters more than the evidence does:
  +13.9pp for pm<1.35 down to -6.8pp for pm>2.10, interpolated in ln(price)
  between bucket centroids and clamped.
- **EDGE_TOLERANCE 0.20**: a quote within 0.20 of the requirement FIRES, with an
  unmissable warning naming the shortfall. This lowers the effective floor to
  1.60. With no quote at all the signal fires unsized - confirmed intended.

Market by scoreline: level -> back to **win**; behind -> the **double chance**
(1X home / X2 away), taken live or derived as `1/(1/fav + 1/draw)`. The blotter
records `market` so settlement grades it correctly.

Adaptive polling is a **quota rescue, not the default**: skipping is off until
65% of the day's allowance is used (`SLOW_POLL_FROM_QUOTA`), then <30 conviction
polls every 4th cycle and <45 every 2nd. A checkpoint window is never skipped.

**Quote plausibility** (`QUOTE_SANITY`, ON since 2026-09-21 as v2): a live quote
below `QUOTE_MIN_RATIO` (0.50) of the PRE-MATCH price is treated as no price, as
is anything <= 1.01. One-sided by design - measured on 39,816 live observations,
the low tail of live/pre-match is tight (p0.1 0.567 level, 0.535 behind) while
the high tail reaches 28x legitimately, so a drift is never penalised. Replayed
over five weeks it rejects 15 of 39,816 quotes, four of which are decimal prices
below 1.00. v1 judged MOVEMENT against the last quote and was disabled the day it
shipped - a goal moves a price more than any movement band allows, and a bad
first sighting became the reference and was defended against the truth.

**A missing price does not block a signal.** It fires unsized (confirmed
intended, 2026-09-19). The `PRICE_CARRY_TTL` (180s) carry covers momentary gaps
but not a half-time suspension, which is ~15 minutes.

**Known and unfixed: the feed's scoreline flickers.** 14.9% of fixture-days
contain at least one poll where the score goes BACKWARDS. While that is live it
changes `goals_needed`, the state (level vs behind - the market AND the
win-probability curve) and the price returned. See TODO.

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
    sleeper.py  InplaySleep task (23:30 daily, retry 15 min to 02:00): sleeps
                the PC unless the heartbeat says the supervisor is still
                working. daily.py only suspends at the end of a day it
                MONITORED, so a blank card left the machine awake all night -
                21-24 Sep 2026, four nights running.
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
