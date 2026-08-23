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
MIN_ODDS = _f("MIN_ODDS", 1.30)          # pre-match favourite band, lower
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
CONV_FIRE_MIN = _f("CONV_FIRE_MIN", 50.0)

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

# --- sizing -----------------------------------------------------------------
BANKROLL = _f("BANKROLL", 20000.0)
COMMISSION = _f("COMMISSION", 0.03)
KELLY_FRAC = _f("KELLY_FRAC", 0.65)      # Kelly is the ceiling, not the target
MAX_STAKE_PCT = _f("MAX_STAKE_PCT", 0.10)   # per-bet cap, fraction of bankroll
MAX_TOTAL_PCT = _f("MAX_TOTAL_PCT", 0.15)   # total open exposure cap
TARGET_WIN = _f("TARGET_WIN", 1000.0)    # base stake targets this profit
MULT_MIN = 0.5
MULT_MAX = _f("MULT_MAX", 2.0)           # conviction multiplier range
CONV_MID = _f("CONV_MID", 50.0)          # conviction that maps to x1.0
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
