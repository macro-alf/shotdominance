"""Configuration: gates, thresholds, sizing, competitions.

Every tunable is overridable by environment variable so the supervisor
(daily.py) and one-off experiments can change behaviour without editing code.
The defaults ARE the current rule set from HANDOVER.md.

IMPORTANT: this file is UTF-8 and contains accented league names (Segunda
Division, Super Lig). Keep it UTF-8. The old build lost two competitions when a
`Get-Content | Out-File` round-trip on Windows PowerShell 5.1 mangled the
accents; PINNED_IDS below is a second line of defence for exactly that.
"""
import io
import os


def _load_dotenv():
    """Populate os.environ from a .env file at the repo root.

    Everything below reads through os.getenv, and nothing else populates it, so
    without this a saved .env is silently inert: the monitor would start with an
    empty API key and fail at the first request. Real environment variables win
    (setdefault), so an explicit export -- or daily.py setting POLL_SECONDS --
    is never overwritten by the file. Absent or unreadable .env is not an error;
    exporting the variables by hand stays a supported way to run.
    """
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    try:
        with io.open(os.path.join(root, ".env"), encoding="utf-8") as fh:
            lines = fh.readlines()
    except OSError:
        return
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, _, value = line.partition("=")
        value = value.strip().strip('"').strip("'")
        if value:
            os.environ.setdefault(name.strip(), value)


_load_dotenv()


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

# --- minimum price for an edge ----------------------------------------------
# REPLACES the time factor in the firing gate (TIME_WEIGHT is now 0). The old
# design multiplied conviction by 1.33 at 45' falling to 1.00 at 75' and then
# compared it to a FIXED floor, which quietly made the floor time-varying: the
# evidence needed to fire was 52.5 at 45' but 70.0 at 75', a third harder late.
# Le Havre 0-0 Angers (2026-09-12) is the worked example - its evidence score sat
# flat at 53-60 for thirty minutes while reported conviction fell 72 -> 53 purely
# as the boost unwound, so it alerted at 2.88-3.25 and went silent at 4.00-5.50.
# The system was structurally buying at the shortest prices the fixture offered.
#
# "Less time to convert" is now expressed where it belongs - in the PRICE. Fewer
# minutes left means a lower chance of the goal the bet needs, so the bet needs
# a longer price to be worth taking. Measured on 2020-23 with penalties stripped
# (rule_ok population, n=1,156 level / 413 behind):
#
#   LEVEL   45' P(win) 59.1% -> break-even 1.71     BEHIND  45' 56.4% -> 1.80
#           75'        32.8% ->            3.12             75' 46.2% -> 2.20
#
# Behind decays far more slowly because the double chance only needs a draw.
MIN_ODDS_GATE = _i("MIN_ODDS_GATE", 1) != 0

# REFITTED 2026-09-14 on a table rebuilt with checkpoints extended to 80 and 85
# (34,734 rows, 2020-23, top-5 leagues, penalties stripped, no API calls - the
# Understat/football-data cache). The 27,635 rows shared with the previous table
# reproduce won / rule_ok / s_vol / s_mom / fav_price exactly; only conv moved,
# because the old table still carried the pre-2026-09-13 time boost.
#
# The fit is on the rule_ok population, so every row is a favourite that PASSED
# the dominance rule - worth about +8pp on its own. Base curves are fitted on
# evidence<70 ONLY; fitting on everything and then adding a bonus double-counts
# the strong cases.
#
# The line holds to 80' and breaks at 85' (residual -6.9pp level, -9.2pp behind),
# which is why there is no checkpoint past 75 and why 85 is not a candidate.
#     residual, evidence<70:  45' -1.9 / -7.2   70' +2.8 / +0.1   85' -6.9 / -9.2
WINP_LEVEL_BASE = _f("WINP_LEVEL_BASE", 0.6019)     # evidence<70, minute 45
WINP_LEVEL_SLOPE = _f("WINP_LEVEL_SLOPE", -0.009466)
WINP_BEHIND_BASE = _f("WINP_BEHIND_BASE", 0.6254)
WINP_BEHIND_SLOPE = _f("WINP_BEHIND_SLOPE", -0.008902)

# THE EVIDENCE BONUS IS FLAT IN TIME. The previous version banded it and set the
# 70'+ band to ZERO on a single cell of n=30. With minutes 80 and 85 measured the
# bonus is positive at every checkpoint, and the "cliff" was one weak cell at 75':
#     45' +7.2   55' +10.3   65' +18.6   75'  +2.7   85' +17.1
#     50' +7.1   60' +12.1   70' +12.2   80' +15.6
# Pooled it is +10.9pp, and splitting it early/late gives +10.7 / +11.4 - i.e. no
# time structure worth modelling. Leave-one-season-out confirms banding buys
# nothing: 0.6697 banded vs 0.6694 flat. Per-cell n is 20-37, so the flat pooled
# figure is also the only one with enough behind it to trust.
# Cost of the old zero: Galatasaray 0-0 Kocaelispor (2026-09-13) was charged 2.66
# at cp70 when the correct bar was the floor.
WINP_STRONG_FROM = _f("WINP_STRONG_FROM", 70.0)
WINP_STRONG_BONUS = _f("WINP_STRONG_BONUS", 0.109)

# PRE-MATCH PRICE, added 2026-09-14. Alf asked whether a heavy pre-match
# favourite differs from a marginal one at the same evidence. It does, by more
# than the evidence itself does, and the model was blind to it. Residual after
# state + minute + evidence:
#     pm <1.35     +13.2pp (n=384)      pm 1.70-2.10   -5.3pp (n=408)
#     pm 1.35-1.70  +0.6pp (n=626)      pm >2.10       -7.0pp (n=461)
# The effect is stable in time (+14.2 early / +11.3 late for heavy favourites),
# so it enters additively rather than as a cross - the cells are far too thin for
# a price x minute x evidence interaction.
#
# Interpolated in ln(price) between the bucket centroids and CLAMPED outside
# them. A straight log-linear fit was tried and rejected: it extrapolates to
# -16.7pp at 3.00 where the measured bucket is -7.0pp, because the relationship
# compresses at long prices.
#
# Leave-one-season-out, each form refitted on the training seasons only:
#     flat bonus, no price  0.6694        flat bonus, + price  0.6609
# Honest caveat: the gain comes from 2020 and 2023; 2021 and 2022 are marginally
# worse. Directionally strong and mechanistically sensible, but not uniform.
WINP_PM_POINTS = [1.236, 1.505, 1.866, 2.343]       # bucket centroids
WINP_PM_ADJ = [0.132, 0.006, -0.053, -0.070]

# The two additive terms PARTLY DOUBLE-COUNT where both are strong, because each
# was measured pooled over the other. Calibration is excellent to 75% and breaks
# above it:
#     predicted 45-55%  n=492  actual 49.6%   gap +0.9
#     predicted 55-65%  n=332  actual 60.5%   gap -1.0
#     predicted 65-75%  n=147  actual 68.7%   gap +0.8
#     predicted 75-100% n= 34  actual 70.6%   gap +9.6   <-- over-confident
# Over-prediction shortens the required price, which is the dangerous direction,
# so the estimate is capped where the calibration stops holding rather than at an
# arbitrary 0.95. Only 34 of 1,879 rows reach the cap. Raise it only with data
# above it, not because a fixture "looks certain".
WINP_MAX = _f("WINP_MAX", 0.75)

# Alf 2026-09-13: NO extra margin over break-even, but never back anything under
# MIN_BACKABLE_ODDS. The percentage margin was doing two jobs badly - it was both
# a safety buffer against a model fitted on 1,569 checkpoints AND the only thing
# stopping a short-priced bet, and it scaled wrongly (10% of a 1.71 break-even is
# 17 cents, 10% of a 2.99 is 30). A flat floor separates them: break-even decides
# WHEN there is value, the floor decides what is worth the trouble at all.
#
# The floor binds early and break-even binds late, which is the right way round:
#     level, evidence<70   45'  break-even 1.71 -> floor 1.80 binds
#                          75'  break-even 2.99 -> break-even binds
# Alf 2026-09-14: 1.85 -> 1.80. With pre-match price in the model the floor binds
# far more often for heavy favourites - a pm 1.22 side at conviction 75 sits on
# the floor at every checkpoint to 75'. Galatasaray missed cp70 by two cents.
#
# Note EDGE_MARGIN 0 means the gate now accepts a ZERO-edge bet wherever
# break-even exceeds the floor, on the model's word alone. The floor is the only
# remaining protection against the probability estimate being optimistic - if
# that proves too permissive, raise MIN_BACKABLE_ODDS rather than reinstating a
# percentage margin, so the two jobs stay separate.
EDGE_MARGIN = _f("EDGE_MARGIN", 0.0)
MIN_BACKABLE_ODDS = _f("MIN_BACKABLE_ODDS", 1.80)

# Alf 2026-09-19: fire when the quote comes within EDGE_TOLERANCE of the required
# price instead of refusing it, and put the requirement in the Telegram alert so
# the shortfall is visible. Absolute, in decimal odds, not a percentage - the
# whole point of the flat floor was that percentages scale wrongly.
#
# THIS LOWERS THE EFFECTIVE FLOOR. `need` is max(break-even, MIN_BACKABLE_ODDS),
# so a tolerance of 0.20 means the shortest backable price is really 1.60, not
# the 1.80 set on 2026-09-14. Raise MIN_BACKABLE_ODDS to 2.00 if 1.80 was meant
# as a hard minimum rather than a target.
#
# Measured against the five days to 2026-09-19: of the 21 settled price refusals,
# 6 were within 0.20 of the bar and would now fire. Those 6 came from 4 fixtures,
# 2 of which won (ADO Den Haag and Werder Bremen, both equalising late).
EDGE_TOLERANCE = _f("EDGE_TOLERANCE", 0.20)

# --- adaptive polling -------------------------------------------------------
# Alf 2026-09-13: pace the dull fixtures much more slowly instead of spending
# the same quota on all of them. A goalless favourite realising nothing at
# conviction 15 costs exactly as much per poll as one at 75, and 62-fixture
# Sundays plan at 97% of the allowance before penalty lookups are counted.
#
# The decision is FREE: the minute comes from the live-fixtures list we already
# fetch, so a skipped fixture costs no /fixtures/statistics call at all.
#
# A fixture is NEVER skipped inside a checkpoint's grace window, so no
# checkpoint can be missed and every fixture has its conviction refreshed at
# least once per checkpoint - which is also what stops a fixture being stranded
# in the slow tier after it improves.
SLOW_POLL = _i("SLOW_POLL", 1) != 0
# Alf 2026-09-14: the slow tiers are a RESCUE, not the normal mode. They were
# throttling from the first poll of the day, which on a 19-fixture Monday meant
# Inter 0-2 down to Udinese - a 1.18 pre-match favourite, the best configuration
# this system looks for - got 3 statistics calls in 21 minutes while the quota
# sat at 15% used. Skipping is now off until the day's allowance is genuinely at
# risk. Below the threshold every watched fixture is measured every cycle.
SLOW_POLL_FROM_QUOTA = _f("SLOW_POLL_FROM_QUOTA", 0.65)
SLOW_POLL_LOW_CONV = _f("SLOW_POLL_LOW_CONV", 30.0)   # below this, poll rarely
SLOW_POLL_LOW_EVERY = _i("SLOW_POLL_LOW_EVERY", 4)
SLOW_POLL_MID_CONV = _f("SLOW_POLL_MID_CONV", 45.0)   # below this, poll half as often
SLOW_POLL_MID_EVERY = _i("SLOW_POLL_MID_EVERY", 2)

# --- penalties --------------------------------------------------------------
# A penalty is a single binary award, not territorial dominance, and it
# contaminates THREE metrics at once. Genoa 0-1 Frosinone (2026-09-12), one poll
# apart with nothing else moving:
#     45'  xg=0.60[0.70]  shots=8  sot=2  box=6   vol=1/4  conv=56
#     45'  xg=1.38[0.70]  shots=9  sot=2  box=7   vol=2/4  conv=83
# +0.78 xG in sixty seconds - more than the whole 45' xG threshold - taking xG
# from 0.86x the bar to 1.94x, hard against the 2x conviction cap, and flipping
# xG from unrealised to realised. A MISSED penalty at that: it manufactured
# evidence of dominance while the score stayed put, which is exactly the state
# the rule hunts for.
STRIP_PENALTIES = _i("STRIP_PENALTIES", 1) != 0

# What one penalty attempt contributes, to be subtracted from the raw feed.
# shots and box are +1 by definition (the spot is inside the area). xG is
# calibrated from the case above: the feed moved 0.60 -> 1.38, so 0.78, which
# also sits in the standard 0.76-0.79 range.
PENALTY_XG = _f("PENALTY_XG", 0.78)

# A converted penalty is on target by definition, so sot -1. A FAILED one may
# have been saved (on target) or missed the goal (not), and API-Football reports
# both as 'Missed Penalty' without distinguishing. In the observed case sot did
# NOT move (2 before, 2 after), so the default assumes off target and leaves sot
# alone. Set to 1 to treat failures as on target instead.
PENALTY_MISSED_ON_TARGET = _i("PENALTY_MISSED_ON_TARGET", 0) != 0

# Discovery costs one /fixtures/events call per fixture per refresh. Measured
# over 07-12 Sep, a per-CHECKPOINT cadence costs 34-314 extra calls a day, i.e.
# 1-5% more - the TODO feared "one call per fixture per POLL", which is an order
# of magnitude worse and is not what this does. First fetch happens as soon as a
# fixture is watched so history is penalty-free from the first snapshot; after
# that it refreshes every PENALTY_REFRESH_MIN match-minutes and stops once the
# match is effectively over.
PENALTY_REFRESH_MIN = _i("PENALTY_REFRESH_MIN", 10)
PENALTY_STOP_MIN = _i("PENALTY_STOP_MIN", 85)

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
# RECALIBRATED 70 -> 50 on 2026-09-13, because the SCALE changed underneath it.
# With TIME_WEIGHT now 0 conviction is pure evidence, and the old 70 was set
# against a score boosted by up to x1.333 - a reported 72 at 45' is only 54 on
# the new scale. Replaying every live signal ever fired proves it: a floor of 70
# on the evidence scale cuts 52 of 56 priced signals, 93%. That is the same trap
# as the 65 episode on 2026-08-31, arrived at from the opposite direction.
#
# The floor's JOB has also changed. It no longer has to guarantee an edge -
# MIN_ODDS_GATE does that, and does it better because it prices the signal
# instead of assuming. What is left for the floor is "is this a real signal at
# all", so it can afford to be permissive. Replayed against the 53 live signals
# that had a quoted price:
#     floor >=50  39 pass the floor, 14 also clear the price  (26% overall)
#     floor >=60  22 pass the floor,  7 also clear the price  (13%)
#     floor >=70   7 pass the floor,  3 also clear the price  ( 6%)
# The price gate removes 25 of the 39 at floor 50 - it is the binding filter,
# which is the intent. Note this also sets the bottom of the stake ladder
# (sizing.size reads CONV_FIRE_MIN), so the weakest permissible signal still
# sizes at STAKE_AT_FLOOR.
# Alf 2026-09-13: nothing below 60 fires, whatever the price says.
CONV_FIRE_MIN = _f("CONV_FIRE_MIN", 60.0)
# RAISED 60 -> 70 on 2026-09-07, on Alf's instruction, to give the WEAKEST
# signal that can fire a stake worth placing. Under half-Kelly with
# conviction inside p, conviction 69.7 at odds 2.00 sizes to exactly 1000;
# below that the model sees so little edge that stakes fall away to nothing
# (conv 60 at 2.00 sized 256, and conv 60 at 1.75 or 4.00 sized ZERO).
# The alternative considered and REJECTED was anchoring conv 60 at a 1000
# stake by scaling: that needs x3.91, i.e. an effective Kelly fraction of
# 1.95 - about twice full Kelly, the point where expected log growth goes
# to zero. Raising the floor buys the same minimum stake by not firing the
# bets that do not deserve it. Cost: on 2026-09-06, four of the six alerts
# fired below 70 (Hearts 61, Gil Vicente 71/91/92, Modena 85/100), so
# expect materially fewer signals.

# time-remaining factor. A dominant favourite that still needs a goal is a better
# bet earlier in the match - more time to convert the dominance. Conviction is
# multiplied by (1 +/- TIME_WEIGHT) around a neutral pivot minute. With the pivot
# at the last checkpoint (75) this is BOOST-ONLY: conviction is raised earlier in
# the match (x1.33 at 45') and left unchanged at 75' - it never suppresses a late
# signal. TIME_WEIGHT=0 disables it; TIME_PIVOT_MIN=60 makes it symmetric.
# TURNED OFF 2026-09-13. Time remaining is now handled by MIN_ODDS_GATE above,
# which demands a longer PRICE late rather than suppressing the SCORE late.
# Leaving both on would double-count time: the old factor already made the
# effective evidence bar 33% harder at 75' than at 45'. Conviction is now a pure
# evidence measure, comparable across minutes - which also means a conviction
# printed at 21' and one printed at 65' finally mean the same thing.
# Set to 0.5 to restore the old behaviour.
TIME_WEIGHT = _f("TIME_WEIGHT", 0.0)
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
KELLY_FRAC = _f("KELLY_FRAC", 0.50)      # Kelly IS the stake now, not a ceiling.
# Lowered 0.65 -> 0.50 on 2026-09-06: the edge is modelled, not measured, and
# fractional Kelly is the hedge against a mis-estimated edge. Overbetting a
# wrong edge is punished far harder than underbetting a right one.
MAX_STAKE_PCT = _f("MAX_STAKE_PCT", 0.10)   # per-bet cap, fraction of bankroll
MAX_TOTAL_PCT = _f("MAX_TOTAL_PCT", 0.15)   # total open exposure cap
TARGET_WIN = _f("TARGET_WIN", 1000.0)    # base stake targets this profit

# --- conviction -> win-probability tilt -------------------------------------
# Conviction now enters the Kelly probability directly instead of scaling a
# separate target-win base. Fitted 2026-09-06 by OLS of won ~ conviction over
# 424 backtest signals (2020-23, five leagues, cp<=75, conv>=60):
#     slope +0.00377 win-probability per conviction point
#     conv 60 -> .494    conv 100 -> .645   (15.1pp spread)
# The tilt is CENTRED on the mean conviction of those signals, so the average
# signal keeps exactly the edge the simulator gives it and only the RELATIVE
# ordering by conviction is new. This is deliberate: the backtest carries only
# PRE-MATCH prices, so it cannot calibrate an absolute edge against the LIVE
# price a bet is struck at. Mean price was flat (1.68-1.83) across conviction
# bands, so the slope is not a price artefact.
CONV_EDGE_SLOPE = _f("CONV_EDGE_SLOPE", 0.00377)
CONV_EDGE_PIVOT = _f("CONV_EDGE_PIVOT", 74.0)

# --- the conviction stake ladder --------------------------------------------
# CHANGED 2026-09-07 on Alf's instruction: the stake is set by CONVICTION ALONE
# and does not vary with the price. Kelly is still computed and reported, but it
# no longer decides the stake.
#
# WHY: under Kelly the stake FALLS as the price lengthens at fixed conviction
# (f = EV/b, and the variance term b grows faster than EV), so a conv-85 signal
# went 2000 at 1.75 down to 1165 at 4.00. Alf does not want a longer price to
# shrink the bet. EV-proportional sizing was considered and rejected for now: it
# is NOT monotonic in odds either, because the simulator's EDGE curve dips above
# 2.50 (.076 -> .052), and fixing that means asserting edge at long prices that
# has never been measured against a LIVE price.
#
# The ladder is linear from the firing floor to a full-conviction bet:
#     conv 70 (CONV_FIRE_MIN) -> STAKE_AT_FLOOR
#     conv 100                -> STAKE_AT_TOP  (the per-bet cap)
STAKE_AT_FLOOR = _f("STAKE_AT_FLOOR", 1000.0)
STAKE_AT_TOP = _f("STAKE_AT_TOP", MAX_STAKE_PCT * BANKROLL)
CONV_STAKE_TOP = _f("CONV_STAKE_TOP", 100.0)
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

# THE BLOCKED-SIGNAL LEDGER, added 2026-09-14. Since the minimum-price gate went
# live it, not conviction, has been the binding constraint - 45 refusals on its
# first afternoon against 2 alerts - and nothing recorded them, so its value
# rested on anecdote. This records every checkpoint where the EVIDENCE rule
# passed but a gate refused, and grades it once the fixture finishes.
# The question it answers is not "did blocked bets win" but "did they win more
# often than the refused price implied": sum pnl_at_quote over settled rows and
# a reliably negative number means the gate is paying for itself.
BLOCKED_LEDGER = _i("BLOCKED_LEDGER", 1) != 0
BLOCKED_LEDGER_PATH = os.getenv("BLOCKED_LEDGER_PATH", "blocked.csv")
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
    # Added 2026-08-31. The ONLY untracked league in the 454-league sweep with
    # both decent core shots (83%) AND xG (83%) - every other candidate was 0%
    # xG. See the watchlist item in TODO.md: the list is otherwise saturated.
    ("Netherlands", "Eerste Divisie"),
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
    # added with the league on 2026-08-31 but the pin was MISSED, so it has been
    # resolving by name ever since - exactly what PINNED_IDS exists to prevent.
    # Caught by test_every_league_is_pinned on 2026-09-13. Id confirmed against
    # a live resolve: "OK Netherlands Eerste Divisie id=89".
    ("Netherlands", "Eerste Divisie"): 89,
}
