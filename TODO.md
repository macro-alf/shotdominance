# Shot-Dominance Monitor — Open Items / Roadmap

Pending work explored but not yet done, roughly by priority. See `STRATEGY.md`
for context. Last updated 2026-08-29.

## MOST URGENT — MOVE THE MONITOR TO THE LAPTOP (Alf abroad 10 days)

- [ ] **RUN THE MONITOR FROM THE LAPTOP.** Raised 2026-08-31. This PC cannot be
  left on. **Deadline is departure.**

  **First, the reassuring part: the monitor does NOT need Claude Code.**
  It is plain Python driven by Windows Task Scheduler — `daily.py` launches
  `monitor.py`, which talks to API-Football and Telegram. Claude Code is only
  the tool used to WORK on it. Nothing about signals, alerts or the blotter
  depends on a Claude session being open, on this machine or any other.
  Claude Code on the laptop is a SEPARATE question: sign in with the same
  account as normal and it works. What does NOT transfer is this session's
  context and its background watchers — those are per-session and will need
  re-creating if you want live commentary while away.

  **Checklist for the laptop:**
  1. Python 3.10 (this PC runs 3.10.11 at
     `%LOCALAPPDATA%\Programs\Python\Python310\python.exe`).
  2. The repo. It already lives in **OneDrive**
     (`C:\Users\Alf\OneDrive\Documents\Local Repos\shotdominance`) so it will
     sync — but WAIT FOR THE SYNC TO FINISH before starting anything.
  3. The three secrets as **User** environment variables: `APIFOOTBALL_KEY`,
     `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`. They are NOT in the repo and will
     NOT sync. Copy them across by hand from this PC's User env vars.
  4. Register `InplayMonitor` (daily 09:45, `python daily.py`, StartIn = repo)
     and `InplayWatchdog` (daily 10:05, repeat 15 min) — but see the watchdog
     item below; it is currently dead, so do not rely on it.
  5. **Task settings that matter on a LAPTOP and default the wrong way:**
     `DisallowStartIfOnBatteries = False` and `StopIfGoingOnBatteries = False`
     (both default to TRUE on a new task — the task simply will not run on
     battery). Also `StartWhenAvailable = True`, `WakeToRun = True`,
     `ExecutionTimeLimit = PT20H`. Principal is `LogonType Interactive`, so the
     laptop must be LOGGED IN, not just powered on.
  6. Disable sleep/hibernate on AC, or the 09:45 start is missed exactly as it
     was on 2026-08-30.

  **THE TRAPS, in order of how badly they bite:**
  - **TIMEZONE. This is the big one.** `daily.py` queries fixtures with
    `TZNAME=Europe/Rome` but schedules against the LOCAL machine clock, and
    picks the fixture date from `datetime.now()`. The task also fires at
    *local* 09:45. Abroad, local 09:45 could be well past the first kickoff, and
    the "today" date could be the wrong day entirely.
    **Simplest safe fix: set the laptop's Windows timezone to W. Europe /
    Europe-Rome and leave it there for the trip.** Everything then behaves
    exactly as it does now. Changing `TZNAME` alone does NOT fix it.
  - **NEVER RUN BOTH MACHINES.** Telegram `getUpdates` is single-consumer, so
    two instances fight over replies and "bet done" can land nowhere. The
    7500/day API quota is also shared per key. Disable the tasks on this PC
    before enabling them on the laptop.
  - **OneDrive will sync `blotter.csv` and `state3.json`.** They are gitignored,
    so git does not carry them — OneDrive does. That is convenient (state
    follows you) and dangerous: `blotter.write()` merges with what is on disk,
    so a half-synced or conflict-copied blotter can lose a settled bet. Confirm
    OneDrive is fully synced before the first laptop run, and again before
    switching back.
  - The watchdog is dead on this PC and copying the task will copy the problem.

  **Verify on the laptop before leaving:** run `python daily.py --dry-run`
  (costs 2 requests) and confirm it lists today's fixtures with sane kickoff
  times in the expected clock. That single command exercises the key, the
  network, the timezone and the league resolution at once.

## URGENT — the safety net is not working

- [ ] **THE WATCHDOG IS DEAD. FIX IT BEFORE ANYTHING ELSE.** Proven 2026-08-30.
  `InplayMonitor` **missed its 09:45 run entirely** — no `daily-2026-08-30.log`,
  heartbeat still reading `2026-08-29T23:46:30 finished`, and the task's
  NextRunTime had already rolled forward to 31 Aug 09:45. Sunday's 69-fixture
  card would have gone completely unwatched. It was only caught because a human
  happened to look at 12:07 and start the task by hand.

  **This is exactly the failure `watchdog.py` was written for** after 2026-08-18:
  a previous-day `finished` heartbeat sitting there during the active window
  hits the `"supervisor never started today"` branch in `diagnose()`, which is
  supposed to Telegram and restart `InplayMonitor`. It did not fire.

  **Evidence it is not merely mis-deciding — it is not RUNNING to completion:**
      08-29 09:08:17  LastTaskResult 267014  nothing written to watchdog.log
      08-30 12:06:48  LastTaskResult 267014  nothing written to watchdog.log
  267014 = 0x41306 = SCHED_S_TASK_TERMINATED. `main()` calls `log()` on EVERY
  path including "outside the active window", so an empty log means it died
  before reaching that line. Last real entry in `logs/watchdog.log` is
  2026-08-28T23:35. It has therefore been silently dead for at least two days,
  through both a missed start (08-30) and a 23-minute feed outage (08-29).

  **Diagnose in this order:** (1) run `python watchdog.py --status` by hand and
  see if it even completes; (2) check the task's ExecutionTimeLimit (PT10M) and
  what it is actually blocking on — `telegram.Telegram()` construction and any
  network call are the suspects; (3) check whether Task Scheduler is killing it
  on resume-from-sleep, since both bad runs were the first run after a wake.
  The Task Scheduler operational log appears to be DISABLED on this machine —
  enable it, or this stays unprovable.

  **NEW CONFLICT, created 2026-08-31 — read before reviving the watchdog.**
  The monitor now starts **13:00 on weekdays, 09:45 at weekends**, but
  `WATCHDOG_ACTIVE_FROM` is a single value of **10**. On a weekday the watchdog
  would therefore be active from 10:00 while the supervisor is not due until
  13:00, see yesterday's `finished` heartbeat during its active window, hit the
  `"supervisor never started today"` branch and **restart `InplayMonitor` at
  10:05 — defeating the 13:00 schedule entirely.** It cannot bite today only
  because the watchdog is dead. **Whoever fixes it MUST make the active window
  day-aware** (13:00+ Mon-Fri, 10:00+ Sat-Sun) or the fix will silently undo
  the schedule. Do not simply set `WATCHDOG_ACTIVE_FROM=13`: that blinds it
  from 09:45 to 13:00 at weekends, which are the busiest days.

  **Also fix the missed-occurrence roll-forward.** `StartWhenAvailable` is True
  but the 08-30 09:45 occurrence was skipped rather than run late. Whatever the
  watchdog does, the monitor task itself should not silently give up on a day.

  Safe to work on TODAY only if the monitor is already running - it shares no
  quota (`--status` makes no API calls).

## High value

- [ ] **MON 31 AUG: SHOULD THE WATCHLIST BE EXTENDED, AND TO WHAT?** Asked for
  by Alf 2026-08-30. **Preliminary answer from data already on disk: there is
  almost nothing left to add, and the real question is what to REMOVE.**

  **The candidate pool is four leagues.** Re-reading `logs/league_coverage.csv`
  (the 454-league sweep of 2026-08-16 — already paid for, free to re-read),
  filtered to leagues we do NOT track that have pre-match odds and >=80% core
  shot coverage:

      core  xg   country       league                    id
      100%   0%  France        Ligue 2                    62   <- deliberately dropped
      100%   0%  Russia        Premier League            235
       83%  83%  Netherlands   Eerste Divisie             89
       80%   0%  Spain         Segunda Division          141   <- deliberately dropped

  Nothing else in 454 leagues clears the bar, and **zero cups** reach 90% core
  shots with odds. Two of the four were dropped on purpose when the list was
  tightened to Tier 1+2. So the watchlist is effectively **saturated**:
  extending means accepting materially worse data, not finding hidden gems.

  **Quota is the binding constraint anyway.** 2026-08-29: 71 fixtures ->
  ~6,429 of 7,500 planned. 2026-08-30: 66 fixtures -> ~6,365 of 7,500. A busy
  weekend already runs at 85% of the allowance, so there is no room to add a
  league without taking one out - and `daily.pace()` budgets on every planned
  fixture, so the cost is real, not notional.

  **THE EVIDENCE POINTS AT SUBTRACTION.** Live in-play availability measured
  over 26,120 watched polls (14-30 Aug) - not the sweep, which sampled FINAL
  totals and therefore flatters everything:

      UEFA Europa League       shots  5%   sot 26%   box  0%   xg 0%
      UEFA Conference League   shots 47%   sot 69%   box 47%   xg 0%
      UEFA Champions League    shots 99%   sot 99%   box 99%   xg 0%

  Europa League is close to unusable. On European nights these dominate the
  card (2026-08-27: 70 of 74 fixtures were UEFA, 0 signals from 990 checkpoints,
  57% of 45' checkpoints unjudgeable). **Dropping Europa League and Conference
  League would free the quota that any addition needs, and remove the worst
  data we carry.** Champions League is fine on core shots and worth keeping.

  **What to actually decide, in order:**
  - **a.** Drop UEFA Europa League and/or Conference League? Measure what they
    have ever contributed: signals fired and checkpoints judged, per
    competition, from `logs/monitor-*.log`. Zero quota.
  - **b.** Only then, spend the freed budget: Eerste Divisie is the only genuine
    addition (83% core AND 83% xG, the sole candidate with xG at all).
    Ligue 2 and Segunda were dropped for a reason - re-read that reason before
    re-adding, and note both are 0% xG so they would run permanently on three
    metrics. Russia: check market access and exchange liquidity before anything
    else, that may settle it.
  - **c.** The sweep is two weeks old and measures FINAL-total availability, not
    live. Any candidate must be re-checked against the LIVE measure before
    adoption - see the availability audit above, which is the right instrument.
  **Do NOT run a fresh 686-competition sweep to answer this.** That is what
  caused the 2026-08-16 outage; the existing CSV answers it for free.

- [x] **TELEGRAM PRICE QUERY — lands at the 31 AUG launch.** Asked for by Alf
  2026-08-30, and the natural companion to dropping the price gate: the alert's
  stake is computed from a BOOKMAKER quote, but the bet goes on an exchange at a
  price only Alf knows, so the sizing has to be askable after the fact.

  **Reply to any alert with a single number** and the monitor answers with the
  stake THAT price implies, at the same conviction:

      you  -> 1.95
      bot  -> SIZING at 1.95  (API quoted 1.73, you found +12.7%)
              Viking 0-1 Aalesund
              conviction 71/100
              Stake: 1368 EUR   [x1.30 on conviction, bound by target-win]
                target-win base 1053, 65%-Kelly cap 1673
                implied 51.3% from the price, model assumes 58.2%

  Nothing is recorded — it is a calculator, not a bet. `'bet done'` still logs
  as before, and a price query while the bot is waiting on `stake price` reminds
  rather than derailing. Implemented as `Monitor.quote()`; the router checks it
  BEFORE the stake+price stage because one number is never a valid pair.
  Exposure from the fixture being quoted is excluded so re-quoting the same
  alert twice does not eat its own room.

  **Open:** the reply shows `model assumes X%` straight from `_edge_at`, which
  is Monte-Carlo output on the OLD rules and explicitly not a measured quantity.
  Displaying it next to a real price makes it look more authoritative than it
  is. Revisit with the Kelly item.

- [x] **LIVE ODDS GATE DROPPED — lands at the 31 AUG launch.** Alf's call
  2026-08-30: API-Football serves BOOKMAKER quotes with overround, the bet goes
  on an exchange at a better price, so refusing a signal on the bookmaker number
  rejects bets that are perfectly available. Viking 0-1 Aalesund the same
  afternoon: vol 3/4, mom 4/4, xG 1.35 v 0.37, shots 14-5 — refused at **1.73,
  two cents under the floor**, on a price Alf could beat.
  `PRICE_GATE=0` (config) now makes the band advisory rather than a veto.
  Measured scope: over 28-30 Aug exactly **24 checkpoints were blocked by price
  alone, ALL of them below 1.75** — roughly 8 extra alerts/day, no ceiling cases.

  **The sizing trap this opens, and how it is closed.** `base = TARGET_WIN /
  (price - 1)`, so a 1.20 quote implies a 5000 base and would have suggested the
  10%-of-bankroll cap — **2000 EUR on a 1.20 shot**. `SIZE_PRICE_CLAMP=1` clamps
  the SIZING price into the band while leaving the signal free: a 1.20 quote
  sizes as if 1.75 (1417 EUR at conv 71), a 6.00 quote as if 4.00. The Telegram
  alert prints the real quote plus an explicit warning to beat it or skip.

  **Still open, and it now matters more:**
  - **a.** The blotter records the price ALF ACTUALLY GOT, so it is the only
    evidence of how far exchange prices beat the API. Once there are enough
    settled bets, compare `price_taken` against `alert_price` and quantify the
    gap. If it is reliably positive, the clamp floor should move with it.
  - **b.** Phase 2 still needs real in-play prices. Dropping the gate removes a
    filter that was standing in for a price model; nothing replaces it yet.
  - **c.** With no price veto, a signal on a genuinely unbackable market now
    reaches Telegram. Watch for alerts nobody can act on and count them.

- [ ] **MON 31 AUG: A MISSING PRICE IS TREATED AS MORE PERMISSIVE THAN A BAD
  ONE.** NOTE: dropping the price gate above largely dissolves this — with no
  veto, "missing" and "bad" both fire. What survives is the SIZING question:
  a missing price still yields stake 0 while a bad one now sizes off the clamp.
  Decide whether a missing price should also size off `PRICE_FLOOR`. Found live 2026-08-30. `engine.py:452` reads
  `price_ok = price is None or (PRICE_FLOOR <= price <= PRICE_CEIL)`, so the
  band is SKIPPED when the feed drops the price. A fixture we can see is quoted
  far below the floor therefore becomes alertable the moment its quote vanishes.

  **Caught red-handed.** Viking 0-1 Aalesund, cp45, four consecutive polls,
  IDENTICAL evidence (vol 2/4, mom 3/4, conv 71) - only the price moved:
      45'  conv 71  odds 1.40   blocked: price outside 1.75-4.00
      45'  conv 71  odds 1.44   blocked
      45'  conv 71  odds 1.44   blocked
      45'  conv 71  odds n/a    -> SIGNAL FIRED, stake 0
  A missing price is strictly LESS information than a bad one, and it produced
  the more permissive outcome. The alert reached Telegram with no stake, on a
  fixture last quoted 1.44.

  **Proposed fix:** carry the last known price forward for the BAND CHECK. The
  engine already carries prices forward <=180s elsewhere (and stats <=300s), so
  the machinery exists - the band check just is not using it. A fixture quoted
  1.44 three polls ago should stay blocked, not become alertable. Only a fixture
  that has NEVER had a price in this match should take the skip path.
  Related and already landing tomorrow: a stake-0 alert no longer spends its
  checkpoint (`engine.py`, committed to the working tree 2026-08-30).

  **28% of checkpoint evaluations have no live price** (2,295 rows, 28-30 Aug),
  so this is not a corner case.

- [ ] **MON 31 AUG: IS THE ODDS-FLOOR DROP ACTUALLY REALISABLE?** Raised by the
  same day's live evidence. The floor drop to 1.01 is measured right on
  PREDICTION (+15.06pp stratified on the 116 recovered signals) but Phase 1
  carries NO in-play prices, so it could not see whether those signals are
  BETTABLE. Three instances on the first afternoon say maybe not:
      Feyenoord (pm 1.14)  conv 85, vol 4/4 mom 4/4  -> odds n/a, stake 0
                           peaked conv 90 at 50' with the price at 1.20
      Viking    (pm 1.20)  conv 71, vol 3/4 mom 4/4  -> quoted 1.40-1.53 all match
      Man Utd   (pm 1.33)  live 1.36 at 20'
  **The hypothesis to test: short pre-match favourites are quoted short IN PLAY
  even while losing and dominating, so the pre-match floor and the live 1.75
  floor were doing the same job.** If true, the recovered population is largely
  unbettable and the honest fix is a LIVE-price-aware watch decision, not a
  pre-match one - watch them, but expect the live band to reject most.
  **Measure from logs, zero quota:** `odds=n/a` rate and out-of-band rate, split
  by pre-match price bucket, over the next week. Do NOT revert the floor on one
  afternoon of evidence - the prediction result stands and three fixtures is
  nothing.

- [x] **MEASURED THE STRONG-EVIDENCE GATE — DONE 2026-08-30. VERDICT: KEEP IT.**
  The live-log evidence below suggested the gate was over-tightening. **It is
  not.** Measured on 2020-23, 5 leagues, 26,530 eligible checkpoints, via a new
  `STRONG_GATE` config flag (default on = live behaviour unchanged):

      gate ON  (live rule)    n=575  win 51.3%  strat lift +9.28pp  z=4.61  BA 222
      gate OFF (pre-24 Aug)   n=824  win 49.4%  strat lift +7.01pp  z=4.16  BA 201

  The gate wins on per-bet lift AND on breadth-adjusted lift. **The 271 signals
  it destroys are worth nothing: +1.14pp stratified, z=0.39** — noise — and flat
  across seasons (+0.6, +2.0, -0.8, +2.9). The shapes it kills are (vol 2,mom 2)
  x93, (0,4) x66, (1,4) x56: exactly the bare-minimum and momentum-only cases it
  was designed for. Torino 0-0 Milan and Hellas Verona were the right calls.

  **Why the live logs misled me.** The +7.1pp "momentum ONLY" figure in the item
  below is from the OLD rule set, before clear-dominance, `goals_needed` and
  volume scaling. Those gates already remove the good momentum-only signals'
  bad neighbours; what the strong gate takes on top is residue. Counting
  rejections (35 in a day) measures nothing without measuring their quality.

  **One caveat that matters.** The backtest has xG on 100% of rows, so
  `n_present=4` always and `STRONG_NEED=3` always applies. LIVE, xG is present
  on only 45% of rows, so more than half the time the gate degrades to 2-of-3.
  **The live gate is WEAKER than the one measured to be good** — which argues
  for fixing xG availability, not for loosening the gate.
  Keep `STRONG_GATE` in place as a measurement tool; do not remove the flag.

- [ ] ~~Original hypothesis (kept for the record, now disproven by the above).~~
  Queued 2026-08-30 off two
  days of live evidence. Shipped 2026-08-24, designed from single days of live
  signals, **never measured against four seasons** — and it is now by far the
  largest rejecter in the system.

  **2026-08-29: 35 distinct checkpoints blocked SOLELY by this gate, across 12
  fixtures, 15 of them with momentum 3/3 (dominant on EVERY in-window metric) —
  against 2 signals fired all day.** A 17:1 block-to-fire ratio.
      Liverpool v Forest      cp60,65,70,75      Servette v Luzern   cp50,55,60,65
      Brest v Toulouse        cp45,50,55,60      Levante v Betis     cp45,50,55
      Heidenheim v Dresden    cp65,70,75         Entella v Cesena    cp55,60,65
      Sassuolo v Torino       cp70,75            Auxerre v Angers    cp45,50
      Real Sociedad v Espanyol cp50,55           + Middlesbrough, Blackburn

  **Why this is not just "the gate working".** Phase 1 measured this exact
  population: `scored: momentum ONLY` n=541, win 49.7%, **lift +7.1pp (z=3.40)**
  — the LARGEST contributor and the HIGHEST lift of any branch. This file
  already says, in terms, "Do not tighten that branch." The 24 Aug gate
  converted it from either/or into both-with-one-strong, which tightens it.

  **AND there is a structural interaction that closes the branch entirely.**
  `goals_needed` multiplies the cumulative bars: at 1-1 it is x2, at 2-2 x3
  (shots bar 31.0 at 48'). Volume then becomes unreachable, so the scored branch
  is momentum-only BY CONSTRUCTION — and `STRONG_NEED` demands volume >= 2.
  Neither gate does this alone; together they make a favourite level at 2-2, or
  behind by two, effectively unable to signal at any level of dominance.
  Levante 2-2 Betis is the worked example: four checkpoints, momentum 3/3 every
  time, never fireable.

  **Measure it, do not argue it.** `backtest/replay.py` calls `rules.evaluate`
  directly, so run 2020-23 with `STRONG_NEED=2` (off) vs 3 (on) and report
  stratified lift, n, and breadth-adjusted lift x sqrt(n) for both, split by
  branch and by scoreline state. Zero quota. If the gate costs breadth without
  buying lift, it should come off or be restricted to the 0-goals branch.
  **The 2014-19 holdout is SPENT — this can be searched, not confirmed.**

- [ ] **MON 31 AUG: DEEP ANALYSIS OF IN-PLAY STAT AVAILABILITY BY LEAGUE.**
  Queued 2026-08-29. **The question this answers: can we keep using API-Football
  at all, or does the strategy require a different provider?** This is the
  prerequisite for the provider item below — do not price up vendors until this
  is done, because it decides whether the problem is fixable by trimming the
  watchlist or is a property of the feed.

  **Why now — the competition-specific theory died within a day.** On 2026-08-28
  the story looked clean: UEFA nights were catastrophic, domestic nights were
  perfect. Then 2026-08-29 broke it.

      day     mix              xG null   stats-from   45' cp lost
      08-27   95% UEFA           99%        10'          57%
      08-28   0% UEFA (evening)   5%        11'           0%
      08-29   0% UEFA (all day)  98%        10'           0%

  **THE 08-29 RESULT KILLS THE COMPETITION THEORY AND REPLACES IT WITH A WORSE
  ONE.** 71 domestic fixtures including Premier League, Bundesliga, Serie A and
  La Liga, and xG was null on 4,570 of 4,671 rows. The 2% that had it all
  arrived in ONE poll late in the evening, each fixture picking xG up at
  whatever minute it happened to be at:
      Sevilla v Atletico     first xg at 46'    (21:30 KO - the only useful one)
      Padova v Verona        first xg at 75'
      Ascoli v Carrarese     first xg at 78'
      Zwolle v NEC           first xg at 79'
      Auxerre, Lyon, Brest   first xg at 90'
  So xG availability is a property of **WALL-CLOCK TIME**, not of competition.
  It came up around 22:30-23:00 after being down all day. You cannot trim the
  watchlist out of a metric that is absent until 22:30. Note also the digest's
  own metric table for the day: `xg  0 pass, 0 abs, 2 dom, 4 both, 1339 missing`
  — xG contributed NOTHING to a single evaluation.
  **Therefore cut the analysis by wall-clock hour FIRST, then by competition.**

  **Two measurement gaps found the same day, fix them before trusting output:**
  - `signalcheck.py` reported `gaps 0%, stats-from 10', lost 0%` for 08-29
    despite a 23-minute total API outage. **It does not see outages at all.**
    Add a poll-level availability measure (blind polls / total polls).
  - **Feed BATCH PUBLISHING manufactures fake momentum.** Fiorentina went from
    8 shots to 13 and 3 box to 7 in a single 60s poll — a backlog landing at
    once. Momentum is a delta over the window, so a batch arrival reads as a
    burst of dominance that never happened. Distinct from plain lateness, and
    the checkpoint-grace fix judges on the post-batch snapshot. Measure how
    often a single poll moves a metric by more than a plausible amount.

  08-29 was 71 domestic fixtures including Premier League and Bundesliga, and
  **xG was null on 465 of 465 rows** — the monitor still flagged
  `[xG NOT SEEN YET]` two hours in, with Liverpool v Nottingham Forest live.
  So "UEFA is the problem" is wrong, or at best incomplete. Untested
  alternatives: an afternoon/evening split (08-28's clean data was evening-only),
  a whole-day feed outage, or season-start xG lag.

  **What to measure** — per competition, and per metric, not pooled:
  - **a.** Minute at which each of xg / shots / sot / box FIRST appears, by
    competition and by kickoff slot (afternoon vs evening). Pooled numbers hid
    this for two weeks.
  - **b.** Share of fixtures whose 45' checkpoint is unjudgeable, by competition.
  - **c.** Share of rows where only ONE metric is present. On 08-27 that was 25%
    of rows, and `NEED=2` makes those fixtures structurally unfireable no matter
    how dominant — see the separate item on NEED not scaling with `n_present`.
  - **d.** Which metrics ever pass. On 08-27 `sot` was the ONLY metric that
    cleared a test all day; `shots` and `box` passed zero times in 982
    evaluations. If three of the four metrics are decorative, the 4-metric rule
    is a fiction and the backtest does not describe the live system.
  - **e.** Whether xG absence is feed-wide on a given day or per-competition —
    the `[xG NOT SEEN YET]` flag answers this cheaply and is already logged.

  **Method.** Start from the logs — `logs/monitor-*.log` back to 08-14 is two
  weeks of free evidence and costs no quota. `signalcheck.py` already computes
  the daily version; extend it to group by competition and kickoff slot rather
  than by day. Only after the log analysis is exhausted, spend quota on a
  controlled probe (`monitor.py --stats` during a major-league match, the
  existing "xG characterisation" item under Medium). **Do not run a sweep on a
  match day** — Saturday 08-29 alone was planned at ~6,429 of 7,500.

  **HARD RULE, set by Alf 2026-08-29: no test, probe or sweep that spends API
  requests may run on a day the monitor is live.** The 7500/day is shared with
  the monitor and there is no headroom on a full card. This audit is designed to
  be answerable from logs alone for exactly that reason; if it turns out a live
  probe is unavoidable, it waits for a no-fixture day or runs after the monitor
  has stopped and the day's remaining quota has been read from `/status`. See
  also "Budget the one-off survey scripts" below — same failure, already cost a
  night's monitoring on 2026-08-16.

  **Decision rule, fixed in advance so the answer is not negotiated after the
  fact.** Target from the provider item: stats from <=15' for >=80% of fixtures.
  - If the failures concentrate in identifiable competitions -> trim the
    watchlist, keep API-Football, no spend.
  - If they concentrate in a time slot or are feed-wide and intermittent -> it
    is an ingest-latency property of the provider; ask their support first
    (costs nothing, and a higher tier will NOT fix a sourcing delay), then price
    up alternatives.
  - If xG specifically is unreliable but core shot stats are not -> consider
    demoting the rule to 3 metrics permanently rather than changing provider.
    Cheaper than a migration, but it is a rule change and therefore needs the
    Phase 1b protocol on fresh seasons.

  **Do not tune thresholds off this.** It is a data-availability audit; the
  binding constraint is whether the numbers arrive, not where the bars sit.

- [x] **FLOOR DROPPED 1.30 -> 1.01 — DONE 2026-08-30, on measurement.**
      band 1.30-3.00 (old)   n=575  win 51.3%  strat lift +9.28pp  z=4.61  BA 222
      band 1.01-3.00 (new)   n=691  win 54.6%  strat lift +9.72pp  z=5.29  BA 256
  The 116 recovered signals score **+15.06pp stratified (z=3.30) on their own** —
  the highest-lift population in the dataset, positive in 4/4 seasons, 86 level
  / 30 behind, concentrated at cp45-cp55. Full rationale and caveats are in the
  comment block at `config.py:MIN_ODDS`. Two objections I raised turned out to
  be wrong and are recorded so they are not re-litigated:
  - **The "sizing hole" does not exist.** `engine.py:479` returns
    `stake=0.0, bound="no price"` when there is no live price, and a live price
    below 1.75 blocks the signal outright. No path produces a large stake.
  - **Quota is not affected.** `daily.pace()` budgets on `len(pending)` — every
    planned fixture — so the band never reduced the estimate. Dropping it spends
    reserve that was always allocated.

- [ ] **MON 31 AUG: TEST `Goalkeeper Saves` AS A REPLACEMENT FOR xG.**
  Asked for by Alf 2026-08-30. Live availability measured over 26,120 watched
  polls (14-30 Aug): **sot 84.4%, shots 80.3%, box 79.8%, xg 45.3%.** xG is
  present less than half the time and is 0% in all three UEFA competitions,
  Allsvenskan, Ligue 2 and Segunda. A 4-metric rule that runs on 3 metrics most
  of the time is not the rule the backtest validated.

  **What the feed actually offers.** Raw `/fixtures/statistics` dump 2026-08-24
  showed **18 entries per team**, of which only NINE were ever recorded:
  `Shots on Goal`(=sot), `Shots off Goal`, `Total Shots`(=shots),
  `Blocked Shots`, `Shots insidebox`(=box), `Shots outsidebox`,
  `Goalkeeper Saves`, `expected_goals`(=xg), `goals_prevented`.
  **The other nine have never been captured.** `apifootball.show_stats`
  (`apifootball.py:358`) prints all types unfiltered but has never been run
  against a live match. **STEP 0: run `python monitor.py --stats` ONCE before
  the monitor starts** (one request) and record all 18. Do not skip this - we
  may be choosing from an incomplete menu.

  **Of the recorded nine, only `Goalkeeper Saves` is a real candidate.**
  `Shots off Goal`, `Blocked Shots` and `Shots outsidebox` are arithmetic
  relatives of what we already have (on+off = total; inside+outside = total), so
  they add almost no independent information. `goals_prevented` is derived FROM
  xG and will therefore be missing exactly when xG is missing - useless as a
  substitute.

  **CHECK THIS FIRST, IT MAY KILL THE IDEA IN AN HOUR.** Saves by the opponent
  keeper are approximately `fav_sot - fav_goals` — every shot on target that did
  not go in was saved. If so, "saves" is very nearly a linear function of a
  metric we already use, and would add breadth (better availability) but almost
  no new information. **This is testable for FREE on the backtest**: Understat
  carries shot outcomes, so reconstruct `saves = opp_sot - opp_goals`, measure
  its correlation with `sot`, and only then measure lift. If r is high, the
  honest conclusion is "better availability, same signal" - which may still be
  worth having, but it is a coverage fix, not a new metric.

  **Then measure, in this order, all on 2020-23 with zero quota:**
  - **a.** Baseline: the current 4-metric rule (n=691, +9.72pp with the new
    odds floor) versus a permanent 3-metric rule with xG REMOVED entirely. If
    dropping xG costs little, that alone is the answer and no substitute is
    needed. Note `STRONG_NEED` falls back to `NEED` at 3 metrics, so this also
    weakens the strong gate — report both effects separately.
  - **b.** 4-metric rule with saves substituted for xG.
  - **c.** 5-metric rule (keep xG when present, add saves).
  Report stratified lift, n, and breadth-adjusted lift for each.
  **The 2014-19 holdout is SPENT — searched, not confirmed.**
  Cross-refs the availability audit above and the `NEED`/`n_present` item below.

- [ ] **DECIDE THE CEILING (`MAX_ODDS`, still 3.00).** Removing it changed the
  backtest by EXACTLY nothing — identical n and lift — because a favourite
  longer than 3.00 barely exists in the five big leagues. The data cannot speak
  to it. Live we track 24 competitions where it can, and above ~3.00 the shorter
  side of a near coin-flip is not really a favourite, which is the thesis rather
  than a threshold. Needs a judgement call, or evidence from a wider league set.
  Original request from Alf 2026-08-29 was to drop the whole filter.

- [ ] ~~Original item, superseded by the two above.~~
  Asked for by Alf 2026-08-29. The band decides who gets WATCHED; the separate
  LIVE price band (1.75-4.00) decides what gets BET. The claim to test is that
  the second one is doing the real work and the first is only costing coverage.

  **What prompted it.** Two fixtures vanished from the monitor entirely on
  2026-08-29 — **Barcelona v Athletic Club** and **Juventus v Parma** — neither
  appearing in a single poll despite being in the plan, in tracked competitions,
  and with every other fixture in their kickoff slot polled normally. Both
  almost certainly priced under the 1.30 floor (the shortest `pm=` seen all day
  was 1.33). `engine.py:382` returns SILENTLY, so this is indistinguishable from
  a fault — see the separate observability item.

  **The argument FOR dropping it is stronger than it looks.** Lift is measured
  STRATIFIED, i.e. net of the base rate in the same (price bucket, minute,
  state) cell. A pure price filter therefore contributes ~0 lift BY
  CONSTRUCTION — that is exactly why the placebo test works. Consistent with
  this, Phase 1b found that widening the cap 2.25 -> 3.00 *lowered* raw win rate
  (51.1% -> 49.5%) while *raising* lift (+6.6 -> +8.1pp). Removing the band
  should therefore add volume without diluting the measured edge. Whether the
  added volume is PROFITABLE is a price question, i.e. Phase 2.

  **What it is not free of:**
  - **a. It is part of the pre-specified Phase 1 rule.** The band is named in
    `STRATEGY.md` as a gate and was fixed before the backtest existed. Changing
    it is a rule change: re-run `backtest/replay.py` with the band removed,
    report baseline and variant side by side, and remember the 2014-19 holdout
    is SPENT so nothing here can be CONFIRMED, only searched.
  - **b. Quota.** The band is checked BEFORE `/fixtures/statistics`
    (`engine.py:382` precedes the stats call), so every fixture it currently
    rejects is a fixture we would start polling for stats every cycle. Saturday
    2026-08-29 was already planned at ~6,429 of 7,500 with the band ON. Measure
    the added fixture count from `logs/daily-*.log` BEFORE changing anything,
    and re-run `daily.pace()` against it. This could be the binding objection.
  - **c. The sizing hole at short prices.** `stake_for` uses
    `TARGET_WIN/(price-1)`, so at 1.15 the base stake is ~6,667 and only the
    10%-of-bankroll cap stops it. The live 1.75 floor normally prevents this -
    BUT the price condition is SKIPPED when no live price is available, and the
    alert still fires. So a very short pre-match favourite with a missing live
    price could alert and size at the cap. Today produced several `odds=n/a`
    rows, so this is not hypothetical. Fix the skip-when-missing behaviour, or
    add an absolute stake sanity check, BEFORE removing the floor.
  - **d. "Favourite" stops meaning much at the top end.** Above ~3.00 the
    shorter side of a near-coin-flip is not really a favourite, and the thesis
    ("a side that SHOULD win is not winning") weakens. Dropping the ceiling is a
    different question from dropping the floor.

  **Suggested staging** rather than one change: (i) drop the FLOOR only, which
  is what actually cost us Barcelona and Juventus; (ii) measure coverage and
  quota impact; (iii) treat the CEILING separately, on backtest evidence. Also
  consider keeping a wide band (say 1.10-5.00) purely as a quota guard rather
  than removing the check outright.

- [ ] **RECALIBRATE HOW CONVICTION IS CALCULATED.** Queued 2026-08-29. The score
  is currently inflated by missing data and barely weighted on dominance, and it
  **drives the stake multiplier**, so this is a money question, not cosmetics.

  **Keep the distinction clear.** Phase 1 validated conviction as a FILTER: the
  rule alone wins 44.9%, the conviction gate lifts it to 51.1%. That result
  stands and must not be broken. What is NOT validated is (i) how the score
  behaves when metrics are missing and (ii) its use as a SIZING input at all.
  Aim the work at (i) and (ii); leave the >=50 gate alone unless the evidence
  says otherwise.

  **Three documented failures, all live:**
  - **Missing metrics INFLATE the score.** `score()` (`rules.py:194`) averages
    over present metrics only, and its `0.4 * min(vals)` weakest-link term has
    no weak link to find when only one value exists. `dom_score` likewise
    returns a flat 100 off one metric with the opponent on zero. **Brann 0-0
    PAOK (2026-08-27) posted conv 88 off three shots on target — its only
    metric — while FC ST. Gallen posted 41 on three metrics including 3/3
    momentum.** Exactly backwards: less evidence should lower confidence.
  - **Dominance is nearly ignored.** At 0.15 weight, a side that shoots a lot
    while being matched shot-for-shot scores highly on a measure that is
    supposed to mean "dominating but not winning". **Levante 1-0 Real Betis
    (2026-08-29, 31'): conv 70 — top of the board — with vol 0/3 and mom 0/3,
    Levante equal or ahead on all three metrics.** Only the clear-dominance
    gate stopped it, and that gate is a separate mechanism bolted on precisely
    because conviction failed to express this.
  - **Rounding makes a legitimate rejection look like an off-by-one.**
    `_fire_decision` (`engine.py:247`) tests `conv < CONV_FIRE_MIN` — correct,
    equality passes — but formats both numbers `%.0f`, so ~49.6 prints as
    `conviction 50 below 50 floor` (Mainz, 2026-08-29 cp75). Cosmetic, but
    `review.py` parses these lines. Print one decimal.

  **Candidates to evaluate (not decisions):**
  - **a.** Scale the score by `n_present`, or refuse to emit a conviction at all
    below some minimum metric count. Ties into the separate `NEED` item — with
    one metric present a fixture is already unfireable, so reporting conv 88 for
    it is pure noise in the logs and in `review.py`.
  - **b.** Raise the dominance weight, or make dominance multiplicative rather
    than additive so that "not dominant anywhere" cannot score 70.
  - **c.** Recompute the weights (currently 0.55 volume / 0.30 momentum / 0.15
    dominance) against measured outcomes rather than assumption. Nobody has ever
    fitted these.
  - **d.** Decouple sizing from conviction entirely until Phase 1b item (a) —
    win rate by conviction decile — actually exists. See the Kelly item,
    sub-item (e): the conviction multiplier [0.5-2.0] is unfitted, and sub-item
    (f) suggests flat stakes until there is a measured edge. **This item and
    that one should be settled together.**

  **Protocol.** Changing the FORMULA is a rule change and needs the Phase 1b
  discipline — and the 2014-19 holdout is SPENT, so a formula refit cannot be
  confirmed until fresh seasons exist. The missing-metric behaviour in (a) is
  arguably a bug fix rather than a tuning change and can be argued on its own
  merits, but say which you are doing and do not smuggle a refit in behind it.
  Backtest note: conviction is computed inside `rules.evaluate`, which
  `backtest/replay.py` calls directly, so any change here silently changes the
  Phase 1 numbers. Re-run the baseline before and after and report both.

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
  match day.** Hardened 2026-08-29 into a standing rule covering every
  quota-spending test or probe, not just coverage sweeps — see the availability
  audit at the top of this section.

- [ ] **FIX: a checkpoint is judged once, on whatever stats happen to exist.**
  Queued 2026-08-22, to land before the monitor launches. `done.add(cp)` marks a
  checkpoint spent at the first poll where `minute >= cp`, so a feed that
  publishes in batches turns each checkpoint into a coin flip on timing.

  **Evidence:** Toulouse 0-0 Lyon, 22 Aug. cp45 judged on `shots=4 xg=0.38` ->
  vol 0/4, mom 0/4, conv 23, consumed. Seconds later, still minute 45, the feed
  published `shots=9 xg=1.57 box=7` -> **vol 2/4, mom 2/4, conv 67, price
  2.50** - clearing every gate. It was the only checkpoint all day that
  qualified, and it was lost to about a minute of feed latency.

  **Fix:** allow a checkpoint to be re-judged while the clock is still inside
  its window (`cp <= minute < cp + 5`) rather than consuming it on first sight.
  Anti-spam does NOT depend on judge-once: `_fire_decision` already requires
  each alert to beat the fixture's previous conviction high, so re-judging
  cannot nag. Put it behind a config flag so it is trivially reversible.

  Smaller and safer than the queued "1b" (evaluate every poll). Do this first -
  it will show whether the full version is even needed.

- [ ] **Should a signal fire when the opponent leads on cumulative xG?**
  Raised 2026-08-22 from FC Zurich 1-1 Basel (conv 54): Basel realised 0 of 4
  cumulative metrics and the opponent had MORE xG, 1.12 vs 0.94. It fired on the
  scored branch via momentum alone, which the rule permits.

  **Already checked - the PATH is fine.** Stratified lift by firing basis over
  2020-23: `scored: momentum ONLY` n=541, win 49.7%, **lift +7.1pp (z=3.40)**
  versus `0 goals: volume AND momentum` n=437, win 52.9%, lift +6.1pp (z=2.60).
  Momentum-only is the largest contributor and carries at least as much real
  lift; its lower RAW win rate is the price/minute confound, since scored
  situations are priced longer and occur later. Do not tighten that branch.

  **What is untested** is the narrower question: an explicit guard on the
  opponent leading cumulative xG. That is a threshold change, so it needs the
  Phase 1b protocol - and the 2014-19 holdout is SPENT, so it needs fresh
  seasons (2010-13 via Understat, or wait for 2026-27) before it can be
  confirmed rather than merely searched.

- [ ] **IF LIVE STATS STAY POOR, PRICE UP ANOTHER PROVIDER.** Raised 2026-08-23.
  **BLOCKED ON the Mon 31 Aug availability audit above** — that item decides
  whether this one is even the right question. Do not contact vendors first.
  The binding constraint has shifted from the rule to the data. `signalcheck.py`
  now measures the number that decides it: **the minute at which shot statistics
  first appear per fixture**, and the share of fixtures whose stats start after
  minute 25 (which makes their 45' checkpoint unjudgeable - no baseline exists).

      day        stats-from   fixtures losing the 45' checkpoint
      08-14..19    10'-15'      0-28%
      08-20        46'          96%
      08-21        26'          50%
      08-22        22'          38%

  Currently **42% overall**. No rule change recovers a checkpoint with no data
  behind it, and 45'-50' is where the time factor gives its largest boost.

  **Before paying anyone**, check whether this is API-Football's ingest latency
  or something plan-related - a higher tier probably will NOT fix a sourcing
  delay, and asking their support costs nothing. Also check whether it is
  competition-specific: West Brom (Championship) had stats from 12' on the same
  day two continental fixtures had none until 45'/47'. If it is concentrated,
  trimming the watchlist to competitions with proven early coverage is far
  cheaper than switching provider (see `logs/league_coverage.csv`).

  **Candidates to evaluate** (latency unverified - do not assume any is better):
  Sportmonks, SportRadar, Stats Perform/Opta (both enterprise-priced), and the
  unofficial SofaScore/FotMob feeds (fast but no ToS cover - not suitable for
  something that sizes real money).

  **The test is already built.** Point a trial key at a day of fixtures, log the
  same rows, and run `python signalcheck.py --print`. Target: stats from <=15'
  for >=80% of fixtures. Do NOT run an evaluation sweep on a match day - it
  shares the 7500/day quota with the live monitor.

- [ ] **`NEED` DOES NOT SCALE WITH `n_present`.** Queued 2026-08-30.
  `rules.py:260` requires `vol_met >= 2 AND mom_met >= 2` no matter how many
  metrics exist. With ONE metric present the ceiling is 1/1, so the fixture is
  unfireable at ANY level of dominance. 2026-08-27: 25% of rows had exactly one
  metric, and 32 evaluations sat at the maximum possible score and could never
  fire — Brann 0-0 PAOK cp45 scored vol 1/1, mom 1/1, conv 88, price 2.00 inside
  the band, and was structurally incapable of alerting.
  The comment at `rules.py:254` says the requirement becomes "NEED of 3" when xG
  is missing — true for 3 metrics, but n=1 was never considered.
  **Blocking on one metric is probably CORRECT.** The defect is that it is
  emergent and unlogged: the console reports it as an ordinary near-miss and
  `review.py` counts it as a real opportunity, which inflates every
  "closest to a trigger" table. Make it explicit and label it, then decide.
  Interacts with the conviction item — a one-metric fixture posting conv 88 is
  noise in the same place.

- [ ] **OBSERVABILITY: silent skips and unmeasured outages.** Queued 2026-08-30.
  Three times in a week the answer to "why isn't X being watched?" required
  reading source: Roma (08-24), Barcelona and Juventus (08-29 — both absent from
  the log all night, near-certainly under the 1.30 pre-match floor, the shortest
  `pm=` seen all day being 1.33). `engine.py:380` (no pre-match favourite) and
  `engine.py:382` (price outside band) both `return` with NO log line, so
  "excluded by design" is indistinguishable from "broken" or "never seen".
  One debug line at each site ends it permanently:
      `Juventus v Parma  skipped: pre-match 1.25 outside 1.30-3.00`
  Keep this even if the odds filter is dropped — the no-favourite path remains.
  Also: **an outage silently destroys momentum windows and therefore signals.**
  On 08-29 Mainz at 69' had vol 2/3, mom 3/3, conv 53, price 2.50, opponent
  leading nothing — a clean pass on every gate — rejected solely for
  `no momentum window >= 20min`, caused by the 16:08-16:38 outage. By the time
  the window rebuilt at 72' momentum had decayed to 1/3. **Half-time makes it
  worse**: the clock freezes, so windows do not rebuild during the break, and
  the whole 16:00 block lost cp45 through cp60. Decide whether snapshot history
  should survive a feed gap, and at minimum log and count what outages cost.

- [ ] **CHECK MON 24 AUG: is the signal drought real?** UPDATED 2026-08-30 —
  the answer is now clearly YES, and it is getting worse. Lifetime rate is 0.4%
  (16 signals / 4,446 checkpoints). **The last three days are 5 from 2,855
  (0.2%), and 08-29 alone was 2 from 1,311 (0.15%) on a 71-fixture card with a
  clean feed** (stats from 10', 0% of 45' checkpoints lost). So this is no
  longer explainable as feed lateness or quiet football — on the best-data day
  in a fortnight the rule fired twice. Both fired signals then LOST (Mainz 0-0,
  Tottenham 0-2), neither taken. Diagnose against the gate census, not by
  loosening thresholds: 08-29 rejections were 67% "volume AND momentum short",
  22% "price outside band", 11% "volume short only" — and separately 35
  checkpoints died on the strong-evidence gate. Settle the strong-gate item
  above FIRST; it is the most likely single cause.
  Original note follows. Three of the last four
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
