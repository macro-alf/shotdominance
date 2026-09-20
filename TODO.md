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

- [ ] **SUN 20 SEP: CONVICTION IS INFLATED WHEN THE MOMENTUM WINDOW IS FABRICATED.**
  Found live the same afternoon the 0.40/0.60 blend shipped. When `approx` is
  set, `window_delta` hands back the WHOLE MATCH in place of a trailing window,
  so `s_mom` is not a momentum score at all - it is cumulative totals wearing a
  momentum label. Conviction is now 60% momentum, so that fabricated number
  dominates the score. Under the old 0.30 weighting it was diluted enough that
  nobody noticed.

  **Three sightings on 2026-09-20, worst first:**

      conv 76  Frosinone 2-0 Como   46'  vol 0/4 mom 0/4  odds 2.62  need 1.80
      conv 70  Frosinone 1-0 Como   39'  vol 0/4 mom 0/4  odds n/a
      conv 78  Frosinone 1-0 Como   24'  vol 0/4 mom 0/4  odds 1.44

  A side TWO GOALS DOWN with ZERO metrics realised, scoring above the 60 firing
  floor and clearing the price gate by 82 cents.

  **Nothing fires today** - `approx` sets `ok=False` in the same function, so
  the evidence rule blocks it before conviction is consulted. The damage is that
  it ranks top of the board on no evidence, and would write a meaningless
  `conviction` into any ledger row. But it is one refactor away from being live:
  the only thing between this and a recommended bet is a separate guard.

  **The fix:** zero or heavily discount conviction when `approx` is set. 60% of
  the score is invented in that state, so reporting a number at all is
  misleading. Zeroing is the honest choice; a cap (say 40) would preserve some
  board ordering if that turns out to matter.
  **Add a test** that `approx` can never produce a conviction over the firing
  floor, so the guard cannot be removed by a later refactor without failing.

  Related: the same fabricated window is why `evaluate()` blocks with
  "no momentum window >= MIN_WINDOW". That block is correct and must stay - this
  item is only about the SCORE, not the gate.

- [x] **EDGE TOLERANCE 0.20 - SHIPPED 2026-09-19, LANDS AT TOMORROW'S LAUNCH.**
  Alf: "if the odds live you see are 0.2 or less away from the minimum required
  odds, still fire the signal and report the minimum odds in Telegram. If no live
  odds, fire the signal anyway. Assuming of course the evidence based conviction
  score is 60 or higher."
  - `EDGE_TOLERANCE = 0.20`, absolute decimal odds, not a percentage.
  - The alert now carries an explicit warning when the quote is short of the bar,
    naming the shortfall and the required price.
  - Firing unsized with no quote is CONFIRMED INTENDED, not a defect. Stop
    raising it; the related "missing price is more permissive than a bad one"
    entry is now a sizing question only.
  - Conviction floor unchanged at 60.

  **CONSEQUENCE ALF SHOULD SEE: the effective floor is now 1.60, not 1.80.**
  `need` is max(break-even, MIN_BACKABLE_ODDS), so the tolerance subtracts from
  the floor too. If 1.80 was meant as a hard minimum, raise MIN_BACKABLE_ODDS to
  2.00. Pinned by `test_the_tolerance_lowers_the_effective_floor`.

  **What it would have changed over the five days to 2026-09-19:** of 21 settled
  price refusals, 6 were within 0.20 and would now fire, from 4 fixtures - 2 of
  which won (ADO Den Haag and Werder Bremen, both late equalisers). The other 2
  lost. So on the only evidence available it is roughly break-even on fixtures
  and adds two bets per five days.

- [x] **MON 14 SEP: ADD A CHECKPOINT AT 80 - MEASURED, DECIDED AGAINST 2026-09-14.**
  The blocker below is RESOLVED: the feature table was rebuilt with checkpoints at
  80 and 85 (34,734 rows, from the local cache, no API calls), so 80' is measured
  rather than extrapolated. The line holds there (residual +1.2pp level, +1.3pp
  behind) and breaks at 85' (-6.9 / -9.2), so 85 is out on its own terms.

  **But the economics say no.** Of 9 distinct fixture-days since launch that
  reached 79-88' passing evidence with conviction >=60, only 3 clear the price
  bar, and all 3 are dead matches the market has written off:

      Modena 0-1 Avellino          79'   2.50 vs 3.46   fail
      Heerenveen 0-0 Telstar       79'   2.60 vs 3.63   fail
      Nordsjaelland 0-0 Silkeborg  79'   2.30 vs 2.91   fail
      Feyenoord 2-2 GO Ahead       82'   2.75 vs 2.90   fail
      Venezia 0-2 Lecce            82'  17.00 vs 4.26   CLEARS
      Cercle Brugge 1-3 Truiden    79'  15.00 vs 3.96   CLEARS

  cp80 would add zero real bets and three bets on matches priced 15-17, where the
  market disagreeing that violently with the model means the model is wrong.
  **Spun out as a NEW item**: `MAX_ODDS` gates the PRE-MATCH price only, and with
  `PRICE_GATE` off there is no live ceiling at all - a 1-3 deficit at 15.00 would
  be backed today if a checkpoint were open. That hole exists with or without cp80.

- [x] ~~Original entry.~~ Asked for by Alf 2026-09-13.
  Checkpoints stop at 75, so a fixture that becomes worth backing after 79' can
  never be alerted. Heerenveen 0-0 Telstar the same day is the case: cp75 expired
  at 79' with the price at 2.60 against 3.85 needed, and by 85' the price had
  drifted to 3.60 against 3.41 needed - **it had become a valid bet with no
  checkpoint left to fire on.**

  **Measured across all logs**: of 3,200 watched rows at 79-88', 101 rows across
  **19 distinct fixtures** had a real momentum window AND passed the evidence
  rule while unjudged. Highest convictions among them:

      Modena v Avellino          79'  conv 67  price 2.50
      Dundee Utd v Falkirk       84'  conv 65  price n/a
      Venezia v Lecce            80'  conv 63  price 15.00
      Heerenveen v Telstar       79'  conv 63  price 2.60
      Nordsjaelland v Silkeborg  79'  conv 62  price 2.30
      Cercle Brugge v St Truiden 79'  conv 60  price 15.00

  **API cost is nil** - those fixtures are already being polled; a checkpoint is
  an evaluation, not a request. The only cost is that `_due_for_poll` never
  skips inside a checkpoint window, so cp80 removes ~5 minutes of skip
  eligibility per fixture.
  **But check the economics before adding it.** At 80' the required price is
  around 3.4 for a level favourite, so most of these fail the edge gate anyway -
  Modena at 2.50 and Heerenveen at 2.60 both would. The two at 15.00 are
  effectively dead matches. So cp80 may add alerts without adding bets; measure
  how many of the 19 would ALSO clear the price bar before shipping it.
  Related: the Medium item "1b - evaluate every poll once eligible" is the
  general version of this. cp80 is the cheap 80% of it.

  **BLOCKER, raised by Alf 2026-09-13: the model has no opinion at 80' that can
  be trusted, and the two versions disagree.** cp80 cannot be evaluated until
  that is settled, because the price bar IS the decision at that stage.
  - **The fit stops at 79'.** Checkpoints run to 75 and grace to 79, so there is
    no observation at 80+. Any number quoted there is extrapolation.
  - **The refit says the price bar at 80' is 3.42 REGARDLESS of conviction**,
    because the measured late evidence bonus was +0.1pp (>=70: 36.7% n=30;
    <70: 36.6% n=227). So conviction 20 and conviction 95 are charged the same.
  - **The live monitor disagrees**: with the old flat +9pp it charges 3.76 at
    conviction 45 and 2.88 at conviction 95 - nearly a point apart, in the
    opposite direction.
  - **The zero is built on n=30.** A bonus worth +15.9pp at 60-69' collapsing to
    +0.1pp at 70-79' is a suspiciously sharp cliff. It may be real (late goals
    are more random) or it may be thin data. Thirty rows should not be trusted
    to zero out a variable that large.

  **So do this first**: widen the late band, or pool 70-90' from the eligible
  population rather than only rule_ok rows, and get a defensible number of
  observations behind the late bonus. Only then decide what cp80's bar should
  be, and only then whether cp80 is worth adding at all.

- [x] **THE BLOCKED-SIGNAL LEDGER - DONE 2026-09-15.** Asked for by Alf. Since
  the minimum-price gate went live on 2026-09-13 it, not conviction, has been the
  binding constraint - 45 refusals on its first afternoon against 2 alerts - and
  nothing recorded them. Its value rested entirely on anecdote.

  `blocked.csv` now records every checkpoint where the EVIDENCE RULE PASSED but a
  gate refused, with the quoted price, the demanded price, P(win), conviction,
  pre-match price and which constraint was binding. It settles from the same
  fixture fetch as the blotter (no extra quota) and grades the refusal exactly as
  a real bet would be graded - outright for 'win', win-or-draw for a double
  chance - so the two tables are comparable.

  **The question it answers is NOT "did blocked bets win."** It is "did they win
  MORE OFTEN than the price we refused implied". A block at 1.83 winning 50% was
  a good block; break-even there is ~55%. `pnl_at_quote` is per unit stake, so
  summing it gives the P&L of the strategy of ignoring the gate - reliably
  negative means the gate is earning its keep, reliably positive means it is
  refusing value. Surfaced as section 7 of the end-of-day report and digest.

  **Do not read it before ~200 settled rows.** The instrument is built; the
  measurement is not made. The temptation after a night like 2026-09-13 - where
  Galatasaray was refused six times and won - will be to act on ten rows.

- [x] **ADAPTIVE POLLING IS A RESCUE, NOT THE DEFAULT - DONE 2026-09-14/15.**
  Alf: "should be used only when quota has reached 65% for the day and we are at
  risk... not for everything from the start". Gated on `SLOW_POLL_FROM_QUOTA`
  (0.65). Verified: full polling at 0/30/50/64% quota, tiering from 65%, and the
  checkpoint window still never skipped even at 95%. The trigger reads the API's
  own used/limit via `_quota_guard`, not the launch-time budget estimate.
  What it cost before the fix: Inter 0-2 down to Udinese, a 1.18 pre-match
  favourite, got three statistics calls in twenty-one minutes on 15% quota, and
  its logged reading sat six minutes stale showing zero shots while the feed had
  2 shots and 0.46 xG. Removing the throttle cost nothing - that evening still
  finished at 2,353 of 7,500.

- [ ] **MON 14 SEP: QUOTA SAVING - TWO OF THE THREE OPTIONS ARE DEAD (2026-09-14).**
  - **(c) widen the skip to the odds call: IMPOSSIBLE.** Odds are a single bulk
    `apifootball.live_prices` call per cycle (`engine.py:472`), outside the
    per-fixture loop. Skipping a fixture saves no odds request. Closed.
  - **(b) stop polling once a fixture CANNOT fire: UNSAFE.** The premise is false.
    Fixtures two goals down reached conviction 60 in **76 rows**, three down in 7.
    Only a four-goal deficit is genuinely dead and that is 0.3% of rows.
  - **(a) a fourth tier below conviction 15: the only real saving.** 35% of rows,
    so halving their rate saves roughly 17% of statistics calls. NOT YET SHIPPED.
    Caveat worth knowing before it is: conviction level carries NO information
    about whether a fixture later reaches 60 - flat at ~14% whether the cut is at
    10, 15, 20, 25 or 30 (785 fixture-days). The tier is a safe way to spend less,
    not a smart one.

- [x] ~~Original entry.~~
  Asked for by Alf 2026-09-13. Adaptive polling shipped today (SLOW_POLL: <30
  every 4th cycle, <45 every 2nd) and worked - up to 10 of 20 watched fixtures
  skipped per cycle, and a 62-fixture Sunday planned at 7,298 of 7,496 finished
  near 5,000. The question is whether it goes far enough.

  **Where the calls actually go, September to date:**

      conviction   rows    share
      <20          7,809     39%
      20-40        7,794     39%
      40-60        2,840     14%
      >=60         1,688      8%

  **78% of every statistics call is spent on fixtures below conviction 40**, and
  the floor to fire is 60. Options, cheapest first:
  - **a.** A fourth tier: below 15, poll every 8th cycle. Those fixtures are
    almost never coming back - measure how often a row under 15 later reaches
    60 before spending more on them.
  - **b.** Stop polling a fixture entirely once it CANNOT fire: at 1-3 down the
    `goals_needed` multiplier puts the volume bars out of reach for the rest of
    the match. That is deterministic, not statistical.
  - **c.** Widen the skip to the odds call as well, not just statistics.
  **Keep the safety property**: never skip inside a checkpoint window, or a
  fixture can be stranded in the slow tier with no way for its conviction to
  refresh. That guarantee is what makes the whole scheme safe and it is pinned
  by `test_a_checkpoint_window_is_never_skipped`.


- [x] **MON 14 SEP: ADD PRE-MATCH PRICE TO THE WIN-PROBABILITY MODEL - DONE 2026-09-14.**
  Shipped with a flat evidence bonus replacing the banded one, the probability
  capped at 0.75, and `MIN_BACKABLE_ODDS` 1.85 -> 1.80 (Alf). Fair
  leave-one-season-out: 0.6694 without price -> 0.6609 with. See the blocks at
  `config.WINP_PM_POINTS` and `config.WINP_MAX`.

  **A defect was found on the way and fixed in the same commit:**
  `WINP_BONUS_LATE = 0.0` was wrong. It rested on one cell of n=30; refitting the
  band gives +8.3pp, and with 80/85 measured the late bonus is +11.4pp. The bonus
  is positive at every checkpoint and flat in time, so it is now one constant.
  Galatasaray 0-0 Kocaelispor was charged 2.66 at cp70 on 2026-09-13 because of
  this; the correct bar was the floor, and the side won 1-0.

- [x] ~~Original entry.~~
  Alf asked 2026-09-13 whether the implied odds condition on how dominant the
  side is, and whether being a heavy pre-match favourite changes things. First
  answer: yes, it conditions on dominance (the fit is on rule_ok, worth ~+16pp).
  Second answer: **pre-match price matters MORE than the evidence does, and the
  model does not use it at all.**

  Level state, 45-49', rule passed:

      pre-match price     P(win)    n     model currently says
      <1.35 heavy fav      67.4%    43          61.3%
      1.35-1.70            64.6%    79          60.3%
      1.70-2.10            55.1%    49          59.8%
      >2.10                50.0%    64          59.9%

  A 17-point spread, and the model returns ~60% for all of them. Restricted to
  strong evidence (vol>=3 and mom>=3) the spread is 24 points:

      <1.50 heavy fav      73.2%    n=56
      1.50-2.10            58.8%    n=51
      >2.10                48.7%    n=39

  For comparison, the EVIDENCE effect at the same minute is small by contrast:
  rule passed 59.1% (n=235) -> vol>=3 and mom>=3 61.6% (n=146) -> a perfect
  4/4+4/4 63.3% (n=49). Most of the value is in passing the rule at all
  (43.1% -> 59.1%), not in passing it emphatically.

  **The error runs both ways, which is why it matters:**
  - heavy favourites: model 61%, actual 67-73% -> required price TOO HIGH, we
    refuse bets that are fine
  - marginal favourites: model 60%, actual 50% -> required price TOO LOW, we
    accept bets that lose

  **Worked example, live 2026-09-13.** Galatasaray 0-0 Kocaelispor, pre-match
  1.22, vol 4/4 mom 4/4 at 50', quoted 1.33. Live model: 64%, needs 1.75,
  blocked by 0.42. With pre-match price as an input: ~73%, needs ~1.38, blocked
  by 0.05. Same decision today, opposite decision at 1.40.

  **Why this variable and not another:** the market's pre-match price is a
  genuine external estimate of team strength, which is exactly what "how likely
  is this side to score" needs and what shot counts only proxy. It is also free
  - `pm=` is already on every log line and every backtest row.

  **Protocol.** This is the FOURTH correction to this model in one afternoon
  (linear fit wrongly blamed, evidence bonus banded, base double-counted, now
  this). Fit it, print the full cell table with n, and show it BEFORE anything
  goes live. Cells here are 39-79, so a three-way interaction of
  price x minute x evidence will be too thin - expect to fit price as a separate
  additive term, not a full cross.

- [x] **TIME MOVED OUT OF CONVICTION AND INTO THE PRICE — DONE 2026-09-13.**
  Alf's design. The old time factor multiplied conviction by 1.333 at 45'
  falling to 1.000 at 75' and then compared it to a FIXED floor, which quietly
  made the floor time-varying: the evidence needed to fire was 52.5 at 45' but
  70.0 at 75'. Le Havre 0-0 Angers (2026-09-12) is the worked example - its
  evidence score sat flat at 53-60 for thirty minutes while reported conviction
  fell 72 -> 53 purely as the boost unwound. It alerted at 2.88-3.25 and went
  silent at 4.00-5.50, i.e. the system was structurally buying at the SHORTEST
  prices the fixture offered.

  **Now:** `TIME_WEIGHT=0`, so conviction is pure evidence and comparable across
  minutes. "Less time to convert" is expressed as a MINIMUM PRICE instead.
  Measured on 2020-23 with penalties stripped (n=1,156 level / 413 behind):

      LEVEL   45' P(win) 59.1% -> break-even 1.71   BEHIND  45' 56.4% -> 1.80
              75'        32.8% ->            3.12           75' 46.2% -> 2.20

  Behind decays far more slowly because a draw settles the double chance.
  Evidence conviction turned out to be FLAT below 70 (48.2 / 48.1 / 48.3% for
  <50 / 50-60 / 60-70) and to jump only above it (57.2%), so it earns one step
  in the model rather than a gradient. Required price = break-even on
  commission, times `EDGE_MARGIN` (10%).

  **`CONV_FIRE_MIN` 70 -> 50, because the scale moved underneath it.** A floor of
  70 on the evidence scale cuts 52 of 56 priced live signals (93%) - the same
  trap as the 65 episode on 08-31, from the other direction. The floor's job is
  now only "is this real"; the price gate decides "does it pay", and it is the
  binding filter: at floor 50, 39 of 53 live signals pass the floor and 14 also
  clear the price.

  Le Havre under the new rule fires at 50', 55', 61', 65', 71' AND 75', each
  against a bar rising 2.04 -> 3.43, instead of going quiet after 55'.

  **What is NOT established.** The probability model is fitted to backtest
  outcomes, and Phase 1 has no in-play prices - so the model says how often
  these bets WIN, never what they were available AT. The whole gate is therefore
  calibrated on one side of the trade. It needs revisiting against real prices
  in Phase 2, and against the blotter's `price_taken` once enough bets settle.
  Cells behind the fit are 15-92, which is why it is a straight line and not
  something cleverer.


- [x] **PENALTIES STRIPPED FROM THE STATS — DONE 2026-09-13.**
  `STRIP_PENALTIES=1`. Penalty attempts, scored and missed, are subtracted from
  xg/shots/sot/box for BOTH sides before anything else sees the numbers.

  **Verified against the real payload**, Genoa v Frosinone (fixture 1550119):
      44+0  Genoa  Var   Penalty confirmed     <- the AWARD, ignored
      45+1  Genoa  Goal  Missed Penalty        <- the SHOT, subtracted
  Only `Goal` events count; taking the VAR row too would double-subtract.

  **Calibrated from the live rows, not from a textbook value:**
      44'  xg=0.60 shots=8 sot=2 box=6      <- before
      45'  xg=1.38 shots=9 sot=2 box=7      <- after
  So one attempt = shots+1, box+1, xg+0.78, and sot UNCHANGED. `PENALTY_XG`
  defaults to 0.78 from that, which also sits inside the standard 0.76-0.79.
  A converted penalty is on target by definition so it takes sot-1;
  API-Football does not distinguish a saved miss from a wild one, and in the
  observed case sot did not move, so `PENALTY_MISSED_ON_TARGET` defaults off.
  Stripping the case above returns exactly the pre-penalty 44' reading.

  **Quota: the objection did not survive measurement.** The worry was one call
  per fixture per POLL. Discovery is per fixture per REFRESH instead - measured
  over 07-12 Sep that is 34-314 extra calls a day, **1-5% more**. The busiest day
  (12 Sep, 5,860 requests) would land at ~6,174 of 7,500.

  **Two subtleties worth keeping:**
  - Subtraction happens BEFORE the snapshot is recorded, or the momentum window
    keeps differencing contaminated history.
  - A penalty found late is retro-subtracted from snapshots already stored at or
    after its minute. Without that, a baseline containing the penalty against a
    corrected current reading would UNDER-report momentum by the penalty's worth.
  - It is applied to the raw feed reading every poll, so it is idempotent.

  Six tests in `tests/test_engine.py` pin all of this.

  **Still open:** the backtest (Understat) has per-shot penalty flags and the
  same exclusion should be applied there before any before/after comparison.
  Nothing has been re-run yet, so every backtest number on file still includes
  penalties.

- [ ] ~~Original entry, kept for the reasoning.~~
  Asked for by Alf 2026-09-12, off a live case.

  **What happened.** Genoa 0-1 Frosinone, one poll apart, nothing else moving:

      45'  xg=0.60[0.70]/0.37  shots=8[10]/4    box=6[5]/1   vol=1/4  conv=56
      46'  xg=1.38[0.71]/0.37  shots=9[10.1]/4  box=7[5.1]/1 vol=2/4  conv=82

  A penalty. +0.78 xG in sixty seconds - MORE THAN THE ENTIRE 45' xG THRESHOLD
  of 0.70 - taking xG from 0.86x the bar to 1.94x, hard against the 2x cap the
  conviction formula allows. That single event flipped xG from unrealised to
  realised and dragged conviction from 56 to 82.

  **Why it is wrong.** The thesis is territorial dominance: a side that SHOULD
  win is not winning, evidenced by sustained shot superiority. A penalty is a
  single binary event awarded for one infringement. It says nothing about
  territorial control, and it contaminates THREE of the four metrics at once -
  xG (+0.78), sot (if on target), and box (a penalty is inside the box by
  definition). A missed penalty is worse still: it adds the same evidence of
  "dominance" while the score stays put, which is exactly the state the rule is
  hunting for.

  **Wanted:** exclude penalty events - scored AND missed - from xg, shots, sot
  and box, for both sides.

  **Known complications, in order of how much they hurt:**
  - **Quota.** `/fixtures/statistics` does not break out penalties; that needs
    `/fixtures/events` (type=Goal detail=Normal/Penalty, plus Missed Penalty).
    That is an EXTRA call per fixture. At peak 33 overlapping on a Saturday
    against a 7500/day budget already planned at 6723, one extra call per
    fixture per poll is NOT affordable. Fetch events only at checkpoints, or
    only once a penalty is suspected (an xG jump > ~0.7 between polls is a
    near-perfect detector and costs nothing).
  - The feed's xG almost certainly INCLUDES penalties, so subtraction is
    needed, not a flag. ~0.76-0.79 per penalty is the standard value; better to
    take the actual figure from the event if the feed gives one.
  - Opponent penalties must be stripped too, or the dominance ratio skews the
    other way.
  - Historical: the backtest (Understat) has penalty flags per shot, so the
    same exclusion can and should be applied there before any comparison.

  **Cheap first step, no quota cost:** log a marker whenever a fixture's xG
  jumps more than 0.7 between consecutive polls. That measures how often this
  actually bites before anyone spends requests fixing it.


- [ ] **SUN 6 SEP: A RE-FIRED ALERT EATS ITS OWN EXPOSURE ROOM AND SHRINKS.**
  Found live 2026-09-06. Modena 0-1 Avellino alerted twice in five minutes:

      45'  conv  85  ->  stake 2000
      50'  conv 100  ->  stake 1000

  Higher conviction, HALF the stake. The first alert reserved 2000 of the 3000
  total exposure room (`MAX_TOTAL_PCT` 0.15 x 20000), and when the SAME fixture
  re-fired, its own reservation was counted against it.

  **The fix already exists five hundred lines away.** The Telegram
  reply-with-a-price path does it correctly:

      engine.py:130   open_total = sum(v for k, v in self.open_pos.items() if k != fid)
                      # "exclude this fixture's own reserved exposure so
                      #  re-quoting the same alert twice does not eat its own room"

  The alert path does not:

      engine.py:553   open_total = sum(self.open_pos.values())

  Same reasoning applies: you place ONE bet on Modena, not two, so the two
  alerts are alternatives and must not be summed. Mirror line 130 at line 553.

  **This BLOCKS the re-firing item above.** If a strong signal keeps alerting
  while its own reservation accumulates against it, the suggested stake decays
  2000 -> 1000 -> 0 and the system reads as losing confidence exactly when
  conviction is highest. The two changes must land together, and the test should
  pin a re-fire at equal-or-higher conviction producing an equal-or-higher stake.

  **Related, NOT a defect:** the same alerts logged `odds=1.50` / `1.53` while
  sizing at 1.75. That is `SIZE_PRICE_CLAMP` doing its job (a bad quote must not
  inflate a stake). Worth a separate look only because the alert then suggests a
  stake computed at a price better than the one actually on offer.


- [ ] **SUN 6 SEP: A STRONG SIGNAL SHOULD KEEP ALERTING, NOT GO SILENT.** Asked
  for by Alf 2026-09-06. Today the firing policy is: fire once above
  `CONV_FIRE_MIN`, then **re-fire only when conviction exceeds the highest
  already alerted for that fixture** (`engine._fire_decision`, pinned by
  `tests/test_engine.py::test_fire_decision_only_repeats_on_a_new_high`).

  **The consequence Alf wants changed.** A fixture that alerts at conv 90 and
  then sits at 85 for the next half hour is SILENT for that whole period, even
  though 85 is a strong signal by every other measure. The rule was written to
  stop a DETERIORATING situation from nagging, and it does that -- but it also
  mutes a situation that is merely no longer setting personal bests. If the
  first alert is missed (phone down, in a meeting), there is no second chance
  while the signal remains excellent.

  **Wanted:** high conviction keeps firing while it stays high.

  **Design constraints, so this does not become spam:**
  - There is ALREADY a mute: replying "bet done" stops alerts for that fixture
    entirely. So repeated alerting is recoverable by the user, which is the main
    argument that this is safe to loosen.
  - Checkpoints are 45..75, so the natural cadence is at most 7 alerts per
    fixture, not one per poll. Re-firing at every checkpoint while conviction
    stays above a HIGH bar is bounded and probably sufficient.
  - Options, roughly in order of how much they change: (a) re-fire whenever
    conv >= a new `CONV_ALWAYS_FIRE` (say 80) regardless of previous high;
    (b) re-fire when conv >= previous_high - tolerance, so small dips do not
    mute it; (c) re-fire on every checkpoint above `CONV_FIRE_MIN` and rely on
    "bet done" alone. (a) is the smallest change that gets what was asked.
  - Whatever is chosen, the alert text should say it is a REPEAT and show the
    conviction trend, or a repeat is indistinguishable from a new signal.

  **Do not lose the thing the current rule protects:** a fixture whose
  conviction is falling should still not re-alert. Falling and high are
  different states and the fix must keep telling them apart.


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

- [ ] **MON 14 SEP: xG DIED ON 1 SEPTEMBER. THE AUDIT'S QUESTION IS WRONG.**
  Measured 2026-09-13 across all 28 days of logs, zero quota. The audit below
  asks "which LEAGUES lack xG". The answer is that it is not a league question
  at all - it is a DATE question, and the date is 1 September.

  **Of 758 fixture-days that reached at least one checkpoint, only 236 (31%)
  had xG on half or more of their checkpoint rows.** The distribution is
  bimodal, not patchy: 514 (68%) never saw xG at a checkpoint and 228 (30%) saw
  it on every single one. Within a fixture it is all or nothing.

      14-16 Aug   33-73%          01-09 Sep    0%  <- nine days, 215 fixtures
      21-24 Aug   84-90%          11 Sep       3%
      28 Aug     100%             12 Sep       8%
      30 Aug      97%             13 Sep       6%
      31 Aug      81%

  Nine consecutive days at EXACTLY zero, then a trickle. Before that, routinely
  80-100% including Serie A and the Bundesliga, which are now at zero. This is a
  step change in what the provider serves, datable to within a day. Three of the
  four earlier zero days (18, 20, 27 Aug) were the UEFA-heavy cards already
  identified - the September collapse is unrelated and spans every competition.

  **Why this matters beyond coverage:**
  - `STRONG_NEED` falls back from 3-of-4 to 2-of-3 whenever xG is absent, so the
    strong-evidence gate has been stuck in its WEAKER form for a fortnight.
  - **Every threshold now live was calibrated on four-metric data.** The
    backtest uses Understat, which is an xG source, so `CONV_FIRE_MIN`, the
    win-probability model and the required-price curve were all fitted where xG
    is always present and are being applied where it never is. That is the same
    class of error as the conviction-floor episode on 08-31: calibrated on one
    distribution, deployed against another.

  **Do first, all free:** re-run the backtest with xG FORCED ABSENT (drop it in
  `reconstruct.build`) and compare lift, signal count and the fitted
  probabilities against the four-metric version. That measures what two weeks of
  three-metric running has actually been doing. Only then decide whether to
  chase the provider.
  **Then ask API-Football directly** - a fortnight of exactly zero on a field
  that previously ran at 100% is a support ticket, not a tuning problem.

- [ ] **MON 31 AUG: DEEP ANALYSIS OF IN-PLAY STAT AVAILABILITY BY LEAGUE.**
  NOTE 2026-09-13: superseded in framing by the item above - the dominant
  variable is the date, not the league. Keep the per-league cuts for the core
  shot metrics, which do still vary by competition.
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
