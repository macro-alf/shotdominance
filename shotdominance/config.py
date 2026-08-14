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
MAX_ODDS = _f("MAX_ODDS", 2.25)          # pre-match favourite band, upper
CHECKPOINTS = [45, 50, 55, 60, 65, 70, 75]
WINDOW = _i("WINDOW", 30)                # trailing momentum window, minutes
NEED = 2                                 # how many of the four metrics must hold
KEYS = ("xg", "shots", "sot", "box")

# baseline thresholds AT minute 45; volume scales * t/45, momentum * WINDOW/45
BASE45 = {"xg": 0.70, "shots": 10.0, "sot": 3.0, "box": 5.0}

# a metric is "realised" only if value >= threshold AND opponent's value on the
# same metric is <= DOM_RATIO of ours.
DOM_RATIO = _f("DOM_RATIO", 0.50)

# conviction caps each ratio-to-threshold at this before scoring: threshold ->
# 50, double-threshold -> 100.
CONV_CAP = _f("CONV_CAP", 2.0)

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
# 24 competitions, resolved to feed league ids at startup by name. PINNED_IDS
# guarantees the two accented ones survive even if name matching fails.
LEAGUES = [
    ("Austria", "Bundesliga"),
    ("Belgium", "Jupiler Pro League"),
    ("Denmark", "Superliga"),
    ("France", "Ligue 1"),
    ("France", "Ligue 2"),
    ("Germany", "Bundesliga"),
    ("Germany", "2. Bundesliga"),
    ("Greece", "Super League 1"),
    ("England", "Premier League"),
    ("England", "Championship"),
    ("Italy", "Serie A"),
    ("Italy", "Serie B"),
    ("World", "UEFA Champions League"),
    ("World", "UEFA Europa League"),
    ("World", "UEFA Europa Conference League"),
    ("Norway", "Eliteserien"),
    ("Netherlands", "Eredivisie"),
    ("Portugal", "Primeira Liga"),
    ("Czech-Republic", "Czech Liga"),
    ("Scotland", "Premiership"),
    ("Spain", "La Liga"),
    ("Spain", "Segunda División"),
    ("Switzerland", "Super League"),
    ("Turkey", "Süper Lig"),
]

# Known feed ids for competitions whose accented names have been lost before.
PINNED_IDS = {
    ("Spain", "Segunda División"): 141,
    ("Turkey", "Süper Lig"): 203,
}
