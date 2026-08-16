# Shot-Dominance Monitor — Open Items / Roadmap

Pending work explored but not yet done, roughly by priority. See `STRATEGY.md`
for context. Last updated 2026-08-16.

## High value

- [ ] **Backtest — Phase 1 (signal validation, no odds).** Reconstruct the 45'–75'
  triggers from **Understat** shot-event data (free; EPL/La Liga/Bundesliga/
  Serie A/Ligue 1 — reconstruct cumulative shots/xG/sot/box per minute) and settle
  on final results. Answers: *does shot dominance while not winning predict the
  team going on to win/draw above base rate?* — independent of pricing.

- [ ] **Backtest — Phase 2 (edge / ROI).** Add **Betfair historical exchange**
  in-play prices (tick-level, downloadable) to Phase 1, matched by teams+date, to
  compute real P&L at prices you'd actually have gotten. API-Football has no
  historical in-play odds, so Betfair is the source.

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
