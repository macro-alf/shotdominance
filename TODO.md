# Shot-Dominance Monitor — Open Items / Roadmap

Pending work explored but not yet done, roughly by priority. See `STRATEGY.md`
for context. Last updated 2026-08-16.

## High value

- [ ] **Backtest — Phase 1 (signal validation, no odds).** Reconstruct the 45'–75'
  triggers from **Understat** shot-event data (free; EPL/La Liga/Bundesliga/
  Serie A/Ligue 1 — reconstruct cumulative shots/xG/sot/box per minute) and settle
  on final results. Answers: *does shot dominance while not winning predict the
  team going on to win/draw above base rate?* — independent of pricing.

- [ ] **Phase 1b — feature exploration: where does the lift live, and can the
  51.8% be raised?** Queued 2026-08-16 after Phase 1 showed +12.5pp (z=4.17).

  **Read this before touching a parameter.** An earlier optimisation pass on
  this project overfit a placebo variable (+119% in-sample → +39.5% out of
  sample). With ~10 tunable knobs, a search WILL find a configuration that
  looks better on 2020-23 and means nothing. The protocol is what makes the
  answer worth having:

  1. **Split before looking.** Understat reaches back to 2014. Explore on
     2014–2019, confirm ONCE on 2020–2023. The holdout is touched a single
     time, at the end. Anything that fails there is dead, not "re-tuned".
  2. **Prefer shape to threshold.** Win rate by conviction decile is stronger
     evidence than any cut point: a monotone curve means conviction carries
     information, whereas a threshold that only works at one value is noise.
     Same for the odds band and the minute.
  3. **Count the comparisons.** Report how many configurations were tried and
     what the best-of-N would look like under the null. An unreported search
     space is how the placebo got through last time.
  4. **Effect must survive, not just persist.** Require the holdout to retain
     most of the exploration lift, not merely stay positive.

  **Win rate is the wrong objective on its own.** Tightening filters raises
  hit rate by discarding signals, which cuts breadth — 60% on 20 bets a season
  is worse than 52% on 300 if the price is right. Judge candidates on lift x
  signal count, and settle it properly against real prices in Phase 2.

  Ordered by prior plausibility, fixed BEFORE running:
  - **a.** Conviction as a continuous predictor (deciles) — is it monotone,
    and where is the knee? `CONV_FIRE_MIN=50` was chosen a priori, never fitted.
  - **b.** Metric decomposition — which of xg/shots/sot/box carries the lift.
    The 2-of-4 rule weights them equally; `sot`/`box` may do the work.
  - **c.** Volume vs momentum branch — which side of the signal predicts.
  - **d.** Minute profile — does the lift decay from 45' to 75'? This is the
    real test of the time-remaining factor, which is currently an assumption.
  - **e.** Odds band — does the lift concentrate inside part of 1.30–2.25?
  - **f.** `NEED` 2→3, and `DOM_RATIO` (expected low value: it is ~4% of
    rejections, so the absolute bars bind instead).
  - **g.** BEHIND / double-chance, currently unproven at n=61 — does it hold
    up with four seasons, or should the strategy drop it and bet level only?

- [ ] **Backtest — Phase 2 (edge / ROI).** Add **Betfair historical exchange**
  in-play prices (tick-level, downloadable) to Phase 1, matched by teams+date, to
  compute real P&L at prices you'd actually have gotten. API-Football has no
  historical in-play odds, so Betfair is the source.

- [ ] **Re-look at Kelly and bet sizing.** Queued 2026-08-16. The sizing stack
  is the least evidenced part of the system and currently sizes real money off
  a number nobody has measured.

  **The core problem:** `stake_for()` sets `p = 1/odds + edge`, where `edge`
  comes from `config.EDGE` — Monte-Carlo output from a simulator run on the
  **old** rules, explicitly "NOT a measured quantity". Kelly on a fabricated
  edge produces a fabricated stake, and 0.65 Kelly reads as conservative only
  if the edge is known. With `p` estimated rather than known, Kelly is
  systematically over-aggressive: the shrinkage should scale with confidence in
  `p`, and confidence is currently nil (n=1 settled bet).

  Specific items:
  - **a.** Kelly is mostly cosmetic today. `size()` takes `min(want, kelly)`
    and `want = TARGET_WIN/(price-1) x mult`, so unless Kelly binds, the real
    rule is "target €1000 profit x conviction". Decide which rule is actually
    in charge and say so. (€1000 target on a €20k bankroll is a 5%-of-bankroll
    profit target per bet.)
  - **b.** `BANKROLL` is a static 20000 and does not track realised P&L — after
    the Norwich loss the true figure is ~19,219. Kelly is a *fraction of current
    wealth*; a frozen bankroll breaks the growth argument in both directions.
  - **c.** Price-source mismatch. Alert prices come from API-Football
    bookmakers, which carry overround, but `p = 1/odds + edge` treats the
    quoted implied probability as if it were fair, and the bet is actually
    placed on an exchange at a different price with 3% commission. Decide which
    price the sizing math is denominated in.
  - **d.** Simultaneous bets are treated as independent — only the 15% total
    exposure cap constrains them. Two live favourites chasing at once are
    correlated (same strategy, often same league window); joint Kelly is
    materially smaller than the sum of singles.
  - **e.** The conviction multiplier [0.5–2.0] (`CONV_MID=50` → x1.0,
    `CONV_TOP=85` → x2.0) is an unfitted assumption. Phase 1b item (a) — win
    rate by conviction decile — is exactly the evidence that would justify,
    reshape or kill it. Do that first, then size off the measured curve.
  - **f.** Until Phase 2 gives a real edge-vs-price estimate, consider **flat
    stakes**. Flat sizing on an unmeasured edge loses very little growth versus
    correctly-sized Kelly, and avoids the ruin risk of Kelly on a wrong `p`.
    It also keeps the blotter clean as a measurement instrument, which is
    currently its main job.

## Medium

- [ ] **"1b" — evaluate every poll once eligible, not only at 5-min checkpoints.**
  Peak dominance often falls between checkpoints (Cercle Brugge peaked at 33'–43').
  Would need re-alert suppression to avoid spam (interacts with the conviction
  rising-only rule).

- [ ] **xG characterisation:** run `python monitor.py --stats` during a major-league
  match to confirm feed-wide vs competition-specific xG behaviour (known-issue #1).

- [ ] **Behind-specific time factor:** optionally make the time boost stronger when
  chasing a deficit (needs a goal in less certain time). Kept uniform in the
  prototype; decide after seeing the current boost-only version in logged data.

- [ ] **Tier-3 cups as 3-metric fillers (optional).** Domestic cups have 100% core
  shots but ~no xG (FA Cup ~88% is the exception). Candidates for midweek CET
  evenings: FA Cup, DFB-Pokal, Copa del Rey, Coupe de France, Carabao Cup, KNVB
  Beker. Round-dependent (early rounds with minnows lack stats). Verify **in-play
  odds** exist for them before betting. See `logs/cup_coverage.csv`.

## Low / later (needs data first)

- [ ] **Threshold tuning:** dominance (`DOM_RATIO=0.50`) is NOT the binding
  constraint (~4% of rejections); the absolute `sot`/`shots` bars are. If more
  signals are wanted, lower `BASE45` sot/shots — but only once the blotter has
  enough settled bets to judge, and **not** by tuning on backtests.
- [ ] **Live-price mapping residual (known-issue #4):** verified Home/Away/Draw +
  live DC map correctly, but the multi-FT-market "last write wins" merge is still
  untested (feeds returned a single FT market per fixture). Watch for implausible
  prices.
- [ ] **Statistical power:** ~1,900 settled bets for 95% CI on a true +10% ROI; a
  single season of P&L carries a ±30% interval. Keep the blotter clean.

## Recently DONE (2026-08-14 → 16)
Clean package rebuild · double-chance-when-behind (+ derived fallback) · conviction
gate (≥50) + rising-only repeats · xG-missing → 2/3 · price & stats carry-forward ·
settle by side + `final_score` · UTF-8 stdout fix (was crashing endday's report) ·
watchlist tightened to Tier 1+2 (dropped Ligue 2 & Spain Segunda, added Ireland &
Allsvenskan) · time-remaining conviction factor (boost-only) · **"1a" early
snapshots (`RECORD_LEAD=5`) — unblocks the momentum branch at the 45' checkpoint**
· `daily.pace()` `WATCH_FROM` derived from the engine gate instead of a stale 30.
