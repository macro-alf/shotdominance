# Shot-Dominance In-Play Monitor — Strategy & State

Handoff summary so a fresh session can continue without prior context. The rule
spec lives in `HANDOVER.md`; architecture/setup in `README.md`; open work in
`TODO.md`. This file is the "what and why" overview. Last updated 2026-08-16.

## The thesis
Back a **pre-match favourite that is dominating the shot count but failing to
win**. The system **alerts only — it never places bets**; you self-report bets by
replying "bet done" in Telegram, and it settles them at full time against the
real result.

## What gets backed
- **Favourite level** (0-0, 1-1): back it to **win** (live win odds).
- **Favourite behind** (0-1, 1-2): back the **double chance** — win *or* draw
  (1X home / X2 away) — taken live, else derived `1/(1/fav_win + 1/draw)`.
  Settled win-or-draw.
- **Favourite leading:** excluded.

## Rule set (current)
- **Watchlist:** 24 competitions (`config.LEAGUES`, all pinned to feed ids).
  Tier 1 = 100% xG + core shot stats; Tier 2 = 100% core, intermittent xG. See
  `logs/league_coverage.csv`.
- **Gates:** competition in list · pre-match favourite decimal **1.30–2.25** ·
  favourite not winning · checkpoints **45,50,…,75** (each judged once).
- **Metrics (4):** xg, shots, sot, box. Baseline at 45': xG 0.70 / shots 10 /
  sot 3 / box 5. Volume threshold scales ×(minute/45); momentum is a constant
  30-min-window bar at ×(30/45).
- **Recording** starts at minute **10** (`CHECKPOINTS[0] − WINDOW − RECORD_LEAD`).
  The 5-min lead-in exists because polls skip minutes, so recording from exactly
  15 landed the first snapshot at 16' — leaving the 45' window with no base,
  flagging it approx and blocking the momentum branch at every 45' checkpoint.
- **Realised** = value ≥ threshold **AND** opponent ≤ 50% of ours (dominance).
  When xG is missing the requirement is **2 of the 3** available metrics.
- **Signal:** favourite not scored → ≥2 volume **AND** ≥2 momentum (an
  incomplete momentum window blocks it). Favourite scored & level/behind → ≥2
  momentum **OR** ≥2 cumulative vs a (goals+1)× bar.
- **Price:** the signal price (win or DC) must be **1.75–4.00**; if no live price
  the condition is skipped and it still alerts. The last live price is **carried
  forward ≤180s** across blocked/suspended polls. Empty **stats** are likewise
  carried ≤300s so a feed gap isn't read as zero.
- **Conviction (0–100):** `0.55·volume + 0.30·momentum + 0.15·dominance` (ratios
  capped at 2×), then **× time_factor**. Time factor is **boost-only**
  (`TIME_WEIGHT=0.5`, `TIME_PIVOT_MIN=75`): ×1.33 at 45' → ×1.00 at 75' — rewards
  earlier dominance (more time to convert), never suppresses a late signal.
  Odds are **deliberately not** in conviction (they drive the filter + sizing).
- **Firing:** only if conviction ≥ **50**, and a live signal re-fires only when
  conviction beats its prior alerted high (no nagging on a fading situation).
- **Sizing:** base `1000/(price−1)` × conviction-multiplier [0.5–2.0], capped by
  0.65-Kelly, 10%/bet and 15% total exposure. Bankroll €20k, commission 3%.
  Blotter records `side` + `final_score`; settlement grades by stored side.

## Architecture
Clean single package (rebuilt from an old seven-file monkeypatch chain):
`shotdominance/` = config · apifootball (API adapter) · rules (pure logic) ·
sizing · telegram · blotter · state · engine (`Monitor`). Top-level entry:
`monitor.py` (poller), `daily.py` (supervisor), `endday.py` (report),
`review.py` (log analyser). One import direction, all state on the `Monitor`
instance. Console log format is byte-stable so `review.py` keeps parsing it; all
entry scripts force UTF-8 stdout. ~48 pytest tests.

## Data reality (important)
- API-Football gives, for a **past** match, only **final** stat totals and
  **pre-match** odds — **no** intra-match stat time series and **no** historical
  in-play odds. So this strategy **cannot be backtested from API-Football** and
  is currently **forward-tested only** via the monitor's own logs.
- xG is a **league (+ in-season UEFA-club)** statistic; domestic cups lack it.
  Completeness vetted 2026-08-16 (`logs/league_coverage.csv`,
  `logs/cup_coverage.csv`). Mid-season sampling under-reports xG (data lags at
  season start) — verify against completed seasons.

## Operations
- Runs via Windows scheduled task **InplayMonitor** (daily 08:00, StartIn = repo,
  `MONITOR_SCRIPT=monitor.py`, `END_ACTION=sleep`). `daily.py` schedules around
  kickoffs, launches `monitor.py`, runs `endday.py`, sleeps the PC; the 08:00
  wake restarts the cycle.
- **Secrets** are Windows **User env vars** (`APIFOOTBALL_KEY`,
  `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`) — never in the repo; the Claude Bash
  tool doesn't inherit them (hydrate from User scope when launching by hand).
- **Same-day deploy:** edit config → stop **both** `daily.py` and the
  `monitor.py` child (killing only daily.py orphans the monitor → double-run) →
  `Start-ScheduledTask InplayMonitor`.
- **One instance per Telegram token** (getUpdates is single-consumer).

## Current state (2026-08-16)
- Live on the current code, watchlist, and time factor.
- **"1a" early-snapshot fix applied** (`RECORD_LEAD=5`). Note `daily.py` launches
  `monitor.py` once per day, 15 min before the first kickoff — it does **not**
  restart between matches, so a config/code change only lands on the next launch
  (or an explicit same-day redeploy).
- First real settled bet: Norwich to win @ 2.60, €781, **LOST** (n=1, noise).
- ~5–6 days of forward logs accumulating in `logs/`.

## What Phase 1 established (2026-08-16)
The signal has **real predictive content**. `backtest/` replays the live rule
(`rules.evaluate` itself, not a reimplementation) over Understat shot events for
2020–2023, five leagues, with the favourite gate taken from football-data.co.uk
pre-match odds. 17,686 eligible checkpoints, 3,178 fixtures, 994 signals:

| population | n | win% | lift |
|---|---|---|---|
| all eligible (base rate) | 17,686 | 37.8% | — |
| rule passed, pre-conviction | 3,276 | 44.9% | +7.1pp |
| **signalled** | **994** | **51.1%** | **+14.1pp (z=8.9)** |
| per match, independent | 754 | 51.6% | +9.1pp (z=4.4) |

Positive in **4/4 seasons** (+8.8 to +17.5pp) and **5/5 leagues** (+12.6 to
+17.1pp). The rule was **pre-specified** — fixed in HANDOVER.md and running live
before this test existed — so nothing here is fitted. The conviction gate earns
its place: rule-alone is 44.9%, conviction lifts it to 51.1%.

**This is not an edge.** A favourite dominating shots has already shortened
in-play; Phase 1 deliberately ignores price. Whether 51.1% beats the price you
would actually get is Phase 2 (Betfair), and nothing before it should drive
sizing.

## What is NOT established (from HANDOVER.md — read it)
- **No measured edge vs price.** Phase 1 shows the signal predicts the
  *outcome*; it says nothing about whether the *price* compensates.
- **The edge curve behind Kelly is Monte-Carlo model output** on the *old*
  rules; it bounds edge between +22% and −0.2% and nobody knows where reality
  sits. Sizing therefore rests on an unmeasured number — see `TODO.md`.
- Detecting a true +10% ROI at 95% confidence needs **~1,900 settled bets**.
- **Do not tune on backtests** — an optimisation pass overfit a placebo variable
  (in-sample +119% ROI → +39.5% out of sample).
