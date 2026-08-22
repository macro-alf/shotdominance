# Shot-Dominance Monitor — Open Items / Roadmap

Pending work explored but not yet done, roughly by priority. See `STRATEGY.md`
for context. Last updated 2026-08-16.

## High value

- [x] **Phase 1b — DONE 2026-08-16. Verdict: keep the rule unchanged.**
  46 candidates searched on 2020–23, confirmed once on an untouched 2014–19
  holdout. The core signal replicated (+5.6pp stratified, z=4.07, n=1,244) but
  **no refinement survived usefully** — the best in-sample rule (56.5% win rate)
  came back at 50.8%, and the two that technically cleared the bar beat the
  baseline by +0.5/+0.6pp while discarding 30–43% of signals. See `STRATEGY.md`.
  Protocol and frozen candidates in `backtest/candidates.py`, run once via
  `backtest/confirm.py` — do not re-run against this holdout with new rules; it
  is spent. A future search needs fresh seasons or a different holdout.

  Still open from this work: **C4**, a broad dominance-only rule (no absolute
  bars) giving 3.3x the breadth at +3.8pp instead of +5.6pp. Breadth-adjusted it
  beats the current rule (244 vs 198). Which is better depends on the price
  each gets, so settle it in Phase 2, not by win rate.

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

- [ ] **Budget the one-off survey scripts.** The 2026-08-16 outage was caused by
  a morning coverage sweep over 686 competitions (455 leagues + 231 cups, ~6–8
  fixtures sampled each) eating most of the 7500/day allowance; the evening
  monitor then hit the wall at ~17:15 and went blind for the rest of the night.
  `daily.py` now reads `/status` and paces against what is actually left, and
  aborts rather than starting blind — but the survey scripts themselves are
  still unbudgeted. Either cap them, run them on a no-fixture day, or have them
  check remaining quota first and stop. **Do not run a full coverage sweep on a
  match day.**

- [ ] **CHECK MON 24 AUG: is the signal drought real?** Three of the last four
  days produced nothing (08-19, 08-21, 08-22); the last three days ran 2 signals
  from 301 checkpoints (0.7%) against a lifetime 2.7%. Some of that is the
  2026-08-21/22 tightening correctly removing fake-momentum signals, some is
  quiet football, and with n=15 lifetime signals the two cannot yet be
  separated. `python signalcheck.py --print` prints the per-day table; a one-shot
  task `InplaySignalCheck` Telegrams it on Mon 24 Aug and self-deletes.

  **If still dry, diagnose before touching anything.** Split blocked checkpoints
  into (a) feed lateness - no usable momentum baseline - versus (b) genuinely
  failing the metric bars. If (a) dominates the fix is data-side (poll stats
  earlier, carry longer, revisit MIN_WINDOW); if (b) dominates it is the
  thresholds, and those must NOT be loosened on a handful of days - see the
  Phase 1b protocol above and the placebo overfit that preceded it.

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
· `daily.pace()` `WATCH_FROM` derived from the engine gate instead of a stale 30
· test suite no longer writes the live `state3.json` · **Backtest Phase 1 —
signal validated, +14.1pp lift (z=8.9) over 2020–23, positive in 4/4 seasons and
5/5 leagues** (see `STRATEGY.md`).
