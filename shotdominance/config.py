"""Configuration: gates, thresholds, sizing, competitions.

Every tunable is overridable by environment variable so the supervisor
(daily.py) and one-off experiments can change behaviour without editing code.
The defaults ARE the current rule set from HANDOVER.md.

IMPORTANT: this file is UTF-8 and contains accented league names (Segunda
Division, Super Lig). Keep it UTF-8. The old build lost two competitions when a
`Get-Content | Out-File` round-trip on Windows PowerShell 5.1 mangled the
accents; PINNED_IDS below is a second line of defence for exactly that.
"""
import os


def _f(name, default):
    return float(os.getenv(name, str(default)))


def _i(name, default):
    return int(os.getenv(name, str(default)))


# --- credentials / endpoint -------------------------------------------------
API_BASE = os.getenv("APIFOOTBALL_BASE", "https://v3.football.api-sports.io")
API_KEY = os.getenv("APIFOOTBALL_KEY", "")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# --- eligibility gates ------------------------------------------------------
# PRE-MATCH FAVOURITE BAND. This decides who gets WATCHED; the separate LIVE
# price band (SIGNAL_MIN/MAX below) decides what can actually be BET.
#
# FLOOR DROPPED 1.30 -> 1.01 on 2026-08-30, on measurement not opinion.
# Backtest 2020-23, 5 leagues, strong gate on throughout:
#     band 1.30-3.00 (old)   n=575  win 51.3%  stratified lift +9.28pp  z=4.61
#     band 1.01-3.00 (new)   n=691  win 54.6%  stratified lift +9.72pp  z=5.29
# The 116 signals the floor was discarding score +15.06pp stratified (z=3.30)
# ON THEIR OWN - the HIGHEST-lift population in the dataset, positive in 4/4
# seasons. Lift is price-stratified, so this is not "short favourites win more":
# they beat the base rate of their OWN price bucket. Live, this also recovers
# fixtures that were vanishing with no log line at all (Barcelona v Athletic and
# Juventus v Parma, both 2026-08-29).
# Caveats kept deliberately visible: 2020-23 is search data and the 2014-19
# holdout is SPENT, so this is searched, not confirmed; season dispersion is
# wide (+0.5, +8.5, +30.4, +19.0pp on 22-35 signals each); and Phase 1 carries
# no in-play prices, so how many of the added signals survive the live 1.75
# floor is unknown until Phase 2.
MIN_ODDS = _f("MIN_ODDS", 1.01)          # pre-match favourite band, lower
# CEILING LEFT AT 3.00 for now. Removing it changed the backtest by exactly
# nothing (identical n and lift) because a "favourite" longer than 3.00 barely
# exists in the five big leagues - so the data cannot speak to it. Live we track
# 24 competitions where it can, and above ~3.00 the shorter side of a near
# coin-flip is not really a favourite, which is the thesis, not a threshold.
MAX_ODDS = _f("MAX_ODDS", 3.00)          # pre-match favourite band, upper
# Widened 2.25 -> 3.00 on 2026-08-23 at Alf's instruction: a side quoted
# 2.99 pre-match that is dominating in play is still the thesis. Note this
# admits weaker favourites, so the volume bars bite harder on them.
CHECKPOINTS = [45, 50, 55, 60, 65, 70, 75]
# A checkpoint used to be spent on the FIRST poll that reached it, on whatever
# statistics existed at that instant. Feeds publish in batches: Toulouse 0-0
# Lyon (2026-08-22) was judged at 45' on shots=4 / conv 23, and seconds later
# the feed showed shots=9, xg=1.57, conv 67 - a clean signal, already thrown
# away. A checkpoint now stays open for this many minutes, re-judged each poll
# until it fires or the window closes. Anti-spam does not depend on judging
# once: _fire_decision already requires each alert to beat the fixture's
# conviction high.
CHECKPOINT_GRACE = _i("CHECKPOINT_GRACE", 4)
WINDOW = _i("WINDOW", 30)                # trailing momentum window, minutes
# Shortest window we will still call momentum. Feeds in Tier 2 competitions
# publish statistics late - Dundalk v Galway (2026-08-21) reported nothing until
# minute 26 - which left the 45'-55' checkpoints with no baseline at all and
# blocked them outright. Rather than lose the earliest checkpoints (the ones the
# time factor deliberately favours), measure the window that IS available and
# scale its bar to match. Below this the sample is too short to mean anything.
MIN_WINDOW = _i("MIN_WINDOW", 20)
NEED = 2                                 # how many of the four metrics must hold

# One side of the evidence must be STRONG, not merely adequate. Torino 0-0 Milan
# (2026-08-23) fired on 2 of 4 volume and 2 of 4 momentum - the bare minimum
# twice over - and Hellas Verona fired on momentum alone with cumulative at 1 of
# 4. A signal now needs STRONG_NEED on the better of the two AND NEED on the
# other. With only three metrics present (no xG) STRONG_NEED falls back to NEED,
# i.e. 2 of 3 on both.
STRONG_NEED = _i("STRONG_NEED", 3)

# Kill switch for the whole gate above, so its COST can be measured against four
# seasons rather than argued from single days. Default True = live behaviour
# unchanged. Note that STRONG_NEED alone cannot turn the gate off: the
# `min(vol, mom) >= NEED` half is what closes the momentum-only branch, and that
# survives any value of STRONG_NEED. Set STRONG_GATE=0 to remove it entirely,
# which restores the pre-2026-08-24 "momentum OR cumulative" scored branch.
STRONG_GATE = _i("STRONG_GATE", 1) != 0

# CLEAR DOMINANCE GATE (2026-08-23). FC Zurich 1-1 Basel fired with the
# favourite realising 0 of 4 cumulative metrics while the OPPONENT led on xG
# (1.12 vs 0.94) - momentum alone carried it through the scored branch. An alert
# is supposed to mean "this side is dominating but not winning", so no signal
# may fire while the opponent is out-performing the favourite on the run of
# play. CUM_DOM_MIN cumulative metrics must be DOMINANT (opponent <= DOM_RATIO
# of ours), whether or not they clear the absolute bar.
CUM_DOM_MIN = _i("CUM_DOM_MIN", 1)
# ...and the opponent must not lead the favourite on any metric that is present.
NO_OPP_LEAD = _i("NO_OPP_LEAD", 1)

# The momentum window at the first checkpoint (45') needs a snapshot at or before
# minute 15. Recording from exactly minute 15 means the first snapshot usually
# lands at 16 (poll granularity plus the moment the fixture goes live), so the
# window base is missing and the 45' checkpoint is permanently flagged approx -
# which blocks the momentum branch outright. Start recording this many minutes
# early so a valid base always exists. Costs a few statistics calls per watched
# fixture; the quota has ample room.
RECORD_LEAD = _i("RECORD_LEAD", 5)
KEYS = ("xg", "shots", "sot", "box")

# How fast the absolute volume bar grows AFTER minute 45. The bar is anchored at
# BASE45 at the 45' checkpoint and used to grow at minute/45, reaching 17.3
# shots by 78' - Manchester City 0-1 Bournemouth (2026-08-23) was dominant on 3
# of 4 metrics (xG 1.55 v 0.55, shots 10 v 4) yet cleared the absolute bar on
# only one, because 10 shots is a lot of football and still under a bar built
# for a higher-tempo match. Halving the growth keeps the 45' anchor but makes
# the later checkpoints reachable. 1.0 restores the old behaviour.
VOL_SCALE_RATE = _f("VOL_SCALE_RATE", 0.5)

# baseline thresholds AT minute 45; volume scales * t/45, momentum * WINDOW/45
BASE45 = {"xg": 0.70, "shots": 10.0, "sot": 3.0, "box": 5.0}

# a metric is "realised" only if value >= threshold AND opponent's value on the
# same metric is <= DOM_RATIO of ours.
DOM_RATIO = _f("DOM_RATIO", 0.50)

# conviction caps each ratio-to-threshold at this before scoring: threshold ->
# 50, double-threshold -> 100.
CONV_CAP = _f("CONV_CAP", 2.0)

# a signal must reach at least this conviction to fire at all, and a live signal
# only re-fires when its conviction exceeds the highest already alerted for that
# fixture (no nagging on a deteriorating situation).
#
# RAISED 50 -> 65 on 2026-08-30, on measurement. The 50 floor was doing nothing:
# on 2020-23, rule-passed checkpoints BELOW 50 carried +8.16pp stratified lift
# and those at or above it carried +8.20pp. It moved raw win rate (43.6% ->
# 50.7%) purely by selecting cheaper, earlier situations - the exact confound
# stratification exists to remove. Conviction only earns its keep at the top:
#     floor >=50 (old)  n=1440  win 50.7%  lift  +8.20pp  breadth-adj 311
#     floor >=65 (new)  n= 850  win 54.2%  lift  +9.34pp  breadth-adj 272
#     floor >=75        n= 424  win 60.8%  lift +14.33pp  breadth-adj 295
# 65 is the point where per-bet lift starts climbing while keeping ~210
# signals/season of breadth. Searched on 2020-23, NOT confirmed - the 2014-19
# holdout is spent. Revisit against real prices in Phase 2, where the
# breadth-versus-edge trade actually gets settled.
# REVISED 65 -> 60 on 2026-08-31, BEFORE 65 ever ran live. The backtest floor
# was calibrated on a conviction distribution the live system does not produce:
# the backtest always has four metrics, while live xG is missing 45% of the
# time and windows are often shortened, both of which depress the score. Every
# signal the monitor has ever fired (33, 14-30 Aug) scored:
#   29 35 36 37 38 46 49 52 53 53 54 58 58 58 59 60 60 61 61 62 62 63 63
#   66 69 70 71 74 74 76 78 85 85
# A 65 floor cuts 23 of 33 (70%), where the backtest predicted 41%. It would
# also have cut TWO of the three winning bets in the blotter (Nordsjaelland
# 57.8, Milan 62.3), turning +1990.87 on 5 settled bets into +59.50 on 2.
# That is n=5 and proves nothing on its own - the backtest evidence is far
# stronger - but "removes 70% of live signals" is a deployment fact the
# measurement could not see. 60 keeps the direction the evidence supports
# (>=60 lifts +8.02pp vs +8.20pp at 50, and 54.2%/+9.34pp at 65) while cutting
# 45% rather than 70%. Re-derive from the LIVE distribution once there are
# enough live signals to do it honestly.
CONV_FIRE_MIN = _f("CONV_FIRE_MIN", 60.0)

# time-remaining factor. A dominant favourite that still needs a goal is a better
# bet earlier in the match - more time to convert the dominance. Conviction is
# multiplied by (1 +/- TIME_WEIGHT) around a neutral pivot minute. With the pivot
# at the last checkpoint (75) this is BOOST-ONLY: conviction is raised earlier in
# the match (x1.33 at 45') and left unchanged at 75' - it never suppresses a late
# signal. TIME_WEIGHT=0 disables it; TIME_PIVOT_MIN=60 makes it symmetric.
TIME_WEIGHT = _f("TIME_WEIGHT", 0.5)
MATCH_END = _f("MATCH_END", 90.0)            # nominal full-time minute
TIME_PIVOT_MIN = _f("TIME_PIVOT_MIN", 75.0)  # minute where the factor is neutral

# --- live price band (favourite to win) -------------------------------------
PRICE_FLOOR = _f("PRICE_FLOOR", 1.75)
PRICE_CEIL = _f("PRICE_CEIL", 4.00)

# PRICE_GATE OFF from 2026-08-31, on Alf's instruction. API-Football's live
# prices are BOOKMAKER quotes carrying overround; the bet is actually placed on
# an exchange, where the price is routinely better. Blocking on the bookmaker
# quote therefore rejects signals that are perfectly bettable in practice -
# Viking 0-1 Aalesund (2026-08-30) sat at vol 3/4, mom 4/4, xG 1.35 v 0.37 and
# was refused at 1.73, two cents under the floor, on a price Alf could beat.
# Over 28-30 Aug exactly 24 checkpoints were blocked by price alone and ALL of
# them were below 1.75, so this is a floor problem, not a ceiling one.
#
# The band is NOT deleted: it still bounds SIZING (see below) and is still
# reported in the alert so the quoted price is visible as a number to beat.
PRICE_GATE = _i("PRICE_GATE", 0) != 0

# Sizing must never be computed off an out-of-band quote. base = TARGET_WIN /
# (price - 1), so a 1.20 quote implies a 5000 base and would suggest the
# 10%-of-bankroll cap (2000 EUR) on a price nobody should take. With the gate
# off, the sizing price is CLAMPED into the band: a 1.20 quote sizes as if 1.75,
# a 6.00 quote as if 4.00. The alert says which price was used.
SIZE_PRICE_CLAMP = _i("SIZE_PRICE_CLAMP", 1) != 0

# --- sizing -----------------------------------------------------------------
BANKROLL = _f("BANKROLL", 20000.0)
COMMISSION = _f("COMMISSION", 0.03)
KELLY_FRAC = _f("KELLY_FRAC", 0.65)      # Kelly is the ceiling, not the target
MAX_STAKE_PCT = _f("MAX_STAKE_PCT", 0.10)   # per-bet cap, fraction of bankroll
MAX_TOTAL_PCT = _f("MAX_TOTAL_PCT", 0.15)   # total open exposure cap
TARGET_WIN = _f("TARGET_WIN", 1000.0)    # base stake targets this profit
MULT_MIN = 0.5
MULT_MAX = _f("MULT_MAX", 2.0)           # conviction multiplier range
# CONV_MID MUST TRACK CONV_FIRE_MIN. It is the conviction that maps to a x1.0
# multiplier, so it has to be the LOWEST conviction that can fire - otherwise
# raising the floor silently inflates every stake. Left at 50 while the floor
# moved to 65, the weakest permissible signal would have sized at x1.43 and the
# multiplier range would have collapsed to [1.43, 2.0]: a 43% across-the-board
# stake rise nobody asked for. Defaulted off CONV_FIRE_MIN so it cannot drift
# again.
CONV_MID = _f("CONV_MID", CONV_FIRE_MIN)  # conviction that maps to x1.0
CONV_TOP = _f("CONV_TOP", 85.0)          # conviction that maps to MULT_MAX

# edge curve (probability points added to 1/odds), interpolated by price. Model
# output from the simulator under "market prices the scoreline only", NOT a
# measured quantity. Extended down to 1.70 so short-priced triggers are sized
# below the per-bet cap instead of pinned to it.
EDGE = [(1.70, .049), (1.85, .062), (2.00, .073), (2.15, .077),
        (2.50, .076), (3.10, .052), (4.00, .051), (5.20, .053)]

# --- polling / pacing -------------------------------------------------------
POLL_SECONDS = _i("POLL_SECONDS", 60)
REQ_PER_MIN = _f("REQ_PER_MIN", 100)

# live odds flicker in and out (blocked/suspended) between polls; reuse the last
# seen price for a fixture for up to this many seconds so a momentary gap does
# not drop the price at the decisive checkpoint.
PRICE_CARRY_TTL = _f("PRICE_CARRY_TTL", 180.0)

# a rate-limited/empty statistics response reads as "0 shots / no opponent",
# which understates dominance. Reuse the last non-empty stats for a fixture for
# up to this many seconds (they only ever accumulate, so a slightly old count is
# a safe floor - far better than a spurious zero).
STATS_CARRY_TTL = _f("STATS_CARRY_TTL", 300.0)

# --- files ------------------------------------------------------------------
# --- feed health ------------------------------------------------------------
# API-Football reports account/entitlement failures INSIDE a 200 body with an
# empty response list, so a lapsed subscription is indistinguishable from a
# quiet evening. On 2026-08-16 the monitor polled blind for ~85 minutes before
# anyone noticed. Alert on Telegram after this many consecutive bad polls, and
# no more often than the cooldown.
FEED_BAD_POLLS = _i("FEED_BAD_POLLS", 3)
FEED_ALERT_COOLDOWN = _f("FEED_ALERT_COOLDOWN", 3600.0)

# --- quota guard ------------------------------------------------------------
# daily.py checks the remaining allowance once, at startup. That is not enough:
# anything else touching the key during the day (a coverage sweep, a manual
# experiment) can drain it while the monitor is mid-session, which is exactly
# how 2026-08-16 went blind at 17:15. So re-check periodically and react before
# the wall rather than at it. /status does not itself count against the quota.
QUOTA_CHECK_POLLS = _i("QUOTA_CHECK_POLLS", 20)   # ~20 min at POLL=60
QUOTA_WARN = _i("QUOTA_WARN", 1200)               # tell Telegram below this
QUOTA_SLOW = _i("QUOTA_SLOW", 700)                # start stretching the interval
QUOTA_POLL_MAX = _i("QUOTA_POLL_MAX", 300)        # slowest we will go

# --- files ------------------------------------------------------------------
BLOTTER_PATH = os.getenv("BLOTTER", "blotter.csv")
STATE_PATH = os.getenv("STATE3", "state3.json")

# --- market filtering (empirical) -------------------------------------------
# Full-time result markets vary by feed. Accept these normalised names, reject
# anything that looks like a period / handicap / prop bet.
FT_MARKETS = {"matchwinner", "fulltimeresult", "1x2", "matchresult", "fulltime",
              "3waybetting", "3wayresult", "winner"}
NOT_FT = ("extratime", "halftime", "firsthalf", "secondhalf", "1sthalf",
          "2ndhalf", "minute", "penalt", "corner", "card", "asian", "handicap")

# Double-chance markets. When the favourite is BEHIND, the tradeable market is
# "favourite win or draw" (1X for a home favourite, X2 for an away one) rather
# than an outright win from behind. Captured live when the feed offers it, else
# derived from the opponent's live win odds.
DOUBLE_CHANCE = {"doublechance", "doublechance1x2"}

# --- competitions -----------------------------------------------------------
# 24 competitions, chosen for statistics completeness (sampled 2026-08-16, see
# logs/league_coverage.csv). Tier 1 = 100% xG + core shot stats for both teams;
# Tier 2 = 100% core with high-but-intermittent xG (the 2-of-3 rule covers the
# xG gaps). Ligue 2 and Spain Segunda were dropped (no xG at all). Resolved to
# feed ids at startup by name, with PINNED_IDS as a guaranteed fallback.
LEAGUES = [
    # Tier 1 - gold-standard leagues
    ("Spain", "La Liga"),
    ("Italy", "Serie A"),
    ("Italy", "Serie B"),
    ("England", "Premier League"),
    ("England", "Championship"),
    ("Germany", "2. Bundesliga"),
    ("Netherlands", "Eredivisie"),
    ("Portugal", "Primeira Liga"),
    ("Turkey", "Süper Lig"),
    ("Greece", "Super League 1"),
    ("Denmark", "Superliga"),
    ("Norway", "Eliteserien"),
    ("Switzerland", "Super League"),
    ("Scotland", "Premiership"),
    ("Austria", "Bundesliga"),
    ("Ireland", "Premier Division"),
    # Tier 1 - UEFA club competitions (gold-standard once past the Aug qualifiers,
    # which get filtered out by the odds/favourite band anyway)
    ("World", "UEFA Champions League"),
    ("World", "UEFA Europa League"),
    ("World", "UEFA Europa Conference League"),
    # Tier 2 - near-gold (100% core shots, high-but-intermittent xG)
    ("Belgium", "Jupiler Pro League"),
    ("Sweden", "Allsvenskan"),
    ("Czech-Republic", "Czech Liga"),
    ("Germany", "Bundesliga"),
    ("France", "Ligue 1"),
]

# Every competition pinned to its current feed id (resolved 2026-08-16) so
# league resolution is bulletproof even if a name or accent drifts in the feed.
PINNED_IDS = {
    ("Spain", "La Liga"): 140,
    ("Italy", "Serie A"): 135,
    ("Italy", "Serie B"): 136,
    ("England", "Premier League"): 39,
    ("England", "Championship"): 40,
    ("Germany", "2. Bundesliga"): 79,
    ("Netherlands", "Eredivisie"): 88,
    ("Portugal", "Primeira Liga"): 94,
    ("Turkey", "Süper Lig"): 203,
    ("Greece", "Super League 1"): 197,
    ("Denmark", "Superliga"): 119,
    ("Norway", "Eliteserien"): 103,
    ("Switzerland", "Super League"): 207,
    ("Scotland", "Premiership"): 179,
    ("Austria", "Bundesliga"): 218,
    ("Ireland", "Premier Division"): 357,
    ("World", "UEFA Champions League"): 2,
    ("World", "UEFA Europa League"): 3,
    ("World", "UEFA Europa Conference League"): 848,
    ("Belgium", "Jupiler Pro League"): 144,
    ("Sweden", "Allsvenskan"): 113,
    ("Czech-Republic", "Czech Liga"): 345,
    ("Germany", "Bundesliga"): 78,
    ("France", "Ligue 1"): 61,
}
