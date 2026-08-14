# shotdominance

In-play football monitor. Watches live matches via API-Football; when a
pre-match favourite is failing to win but dominating the shot count, it sends a
Telegram alert with a stake suggestion.

**It never places bets.** It alerts, and records bets you tell it you placed.

This is a clean single-package rebuild of an earlier seven-file monkeypatch
chain (`monitor2 → run4 → run5 → run6 → run7/monitor3`). The rule set is
unchanged (see [HANDOVER.md](HANDOVER.md) for the full specification and the
important caveats); the API-adapter details were carried over verbatim because
they were established empirically against the live feed.

## Layout

```
monitor.py            entry point: --stats / --once / run forever
daily.py              supervisor: arm for the day, launch the monitor, report, sleep
endday.py             end-of-day report + pasteable digest + Telegram summary
review.py             log analyser (stdlib only) — recomputes WHY each metric failed
shotdominance/
  config.py           gates, thresholds, sizing, competitions (all env-overridable)
  apifootball.py      API client (pacing + rate-limit backoff), odds, stats, leagues
  rules.py            pure rule engine: thresholds, dominance, momentum, conviction
  sizing.py           Kelly ceiling + target-win × conviction multiplier
  telegram.py         two-way Telegram (send + getUpdates)
  blotter.py          the CSV bet record and settlement
  state.py            crash-safe JSON persistence
  engine.py           the Monitor: one object owning all cross-poll state
tests/                pinning tests for the rules and sizing
```

The old build worked but was fragile: each layer reached into the module below
and rebound its functions, and `monitor3` even rebound `run5._orig_poll` to keep
the pacing wrapper alive — a single import-order change broke it silently. Here
there is one import direction (`engine` depends on the leaf modules, nothing
depends back), and all mutable state lives on a `Monitor` instance.

## Setup

1. **API-Football** (api-sports.io) Pro plan — 7,500 requests/day.
2. **Telegram bot** via BotFather; get the chat id from `getUpdates`.
3. Set environment variables (persist them for the scheduled task):

   ```
   APIFOOTBALL_KEY      your api-sports.io key
   TELEGRAM_BOT_TOKEN   BotFather token
   TELEGRAM_CHAT_ID     your chat id
   END_ACTION           sleep | restart   (what daily.py does when the day ends)
   ```

   Everything in `config.py` is overridable the same way (`POLL_SECONDS`,
   `DOM_RATIO`, `BANKROLL`, `KELLY_FRAC`, `MIN_ODDS`/`MAX_ODDS`, …).

4. Install and run:

   ```bash
   pip install -r requirements.txt
   python monitor.py --stats     # dump the feed's stat types (settles the xG question)
   python monitor.py --once      # one poll and exit
   python daily.py --dry-run     # print today's plan (costs ~2 requests)
   python daily.py               # arm for the day
   ```

5. Windows scheduled task, daily 08:00, with `-WakeToRun`, plus
   `powercfg -setacvalueindex SCHEME_CURRENT SUB_SLEEP RTCWAKE 1`.

Quota: a heavy Saturday costs roughly 2,800–3,200 of 7,500 requests at 60s
polling; `daily.py` paces `POLL_SECONDS` to fit the day inside the budget.

## Acknowledging a bet

Alerts repeat at every checkpoint while the signal holds. Reply **`bet done` as
a reply to that specific Telegram alert**; the bot then asks for stake and price,
writes `blotter.csv`, and settles the bet at full time.

## Tests

```bash
pip install pytest
python -m pytest
```

The tests pin the spec: the dominance test, the conviction scale (threshold →
50, double → 100), the 0-0 AND branch, the scored EITHER/OR branch, checkpoint
bookkeeping, and the sizing clamps.

## A standing caveat

There is **no measured edge** yet. Everything about expected value comes from a
Monte Carlo simulation. `blotter.csv` is the first instrument that can answer the
question, and it needs a few hundred settled bets before it says anything that
is not noise. Read the "What is NOT established" section of
[HANDOVER.md](HANDOVER.md) before trusting any number this produces.
