"""Phase-1 data sources: Understat shot events + football-data.co.uk odds.

Two independent free sources, both cached to disk on first fetch so a re-run
costs nothing and the sites are hit once per object:

  Understat            shot-level events (minute, result, X/Y, xG) per match.
                       `getLeagueData/<league>/<season>` -> fixture list,
                       `getMatchData/<id>`               -> shots.
                       (The league/match PAGES no longer embed the data as
                       `JSON.parse(...)`; they fetch these endpoints by ajax.
                       Verified 2026-08-16.)

  football-data.co.uk  pre-match bookmaker odds, one CSV per league-season.

WHY NOT Understat's own `forecast` FOR THE FAVOURITE GATE
  Each fixture carries a w/d/l `forecast`, which looks like a free pre-match
  probability. It is not: Burnley v Man City 2023-08-11 reads l=0.897, far too
  extreme for a pre-match view, because it is simulated FROM that match's own
  shots. Gating on it would leak the result into the gate. Use real bookmaker
  odds.

WHY NOT API-Football FOR THE ODDS
  It does carry pre-match odds for past fixtures, but at one request per
  fixture it would burn the daily quota the live monitor needs, for odds that
  football-data gives in bulk for free.
"""
import csv
import datetime as dt
import io
import json
import os
import re
import time

import requests

CACHE = os.getenv("BACKTEST_CACHE", "backtest_cache")
UA = {"User-Agent": "Mozilla/5.0 (compatible; shot-dominance research)",
      "X-Requested-With": "XMLHttpRequest"}
POLITE_SECONDS = float(os.getenv("BACKTEST_DELAY", "1.0"))

UNDERSTAT = "https://understat.com"
FOOTBALL_DATA = "https://www.football-data.co.uk/mmz4281"

# Understat league key -> football-data.co.uk division code
LEAGUES = {
    "EPL": "E0",
    "La_liga": "SP1",
    "Bundesliga": "D1",
    "Serie_A": "I1",
    "Ligue_1": "F1",
}

_last_call = [0.0]


def _polite():
    """One request per POLITE_SECONDS, shared across both hosts."""
    wait = POLITE_SECONDS - (time.time() - _last_call[0])
    if wait > 0:
        time.sleep(wait)
    _last_call[0] = time.time()


def _cached(name, fetch, binary=False):
    """Fetch once, then serve from disk forever. Historical data never changes."""
    path = os.path.join(CACHE, name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            return fh.read()
    _polite()
    text = fetch()
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    return text


def _get(url):
    r = requests.get(url, headers=UA, timeout=45)
    r.raise_for_status()
    return r.text


# --- Understat --------------------------------------------------------------
def league_fixtures(league, season):
    """Every fixture of a league-season: id, teams, date, final goals."""
    raw = _cached("understat/%s-%s.json" % (league, season),
                  lambda: _get("%s/getLeagueData/%s/%s" % (UNDERSTAT, league, season)))
    return json.loads(raw)["dates"]


def match_shots(match_id):
    """Shot events for one match, as {'h': [...], 'a': [...]}."""
    raw = _cached("understat/match-%s.json" % match_id,
                  lambda: _get("%s/getMatchData/%s" % (UNDERSTAT, match_id)))
    return json.loads(raw)["shots"]


# --- football-data.co.uk ----------------------------------------------------
def _fd_season(season):
    """Understat season 2023 (=2023/24) -> football-data path '2324'."""
    y = int(season)
    return "%02d%02d" % (y % 100, (y + 1) % 100)


def odds_rows(league, season):
    """Pre-match odds rows for a league-season, keyed nowhere yet - raw dicts."""
    div = LEAGUES[league]
    raw = _cached("footballdata/%s-%s.csv" % (div, _fd_season(season)),
                  lambda: _get("%s/%s/%s.csv" % (FOOTBALL_DATA, _fd_season(season), div)))
    rows = [r for r in csv.DictReader(io.StringIO(raw)) if r.get("HomeTeam")]
    return rows


def parse_fd_date(s):
    for fmt in ("%d/%m/%Y", "%d/%m/%y"):
        try:
            return dt.datetime.strptime(s.strip(), fmt).date()
        except ValueError:
            continue
    raise ValueError("unparseable football-data date: %r" % s)


# --- joining the two --------------------------------------------------------
# Understat uses full club names, football-data uses short ones. Normalisation
# handles most; these are the residue that normalisation cannot reach. Built by
# running the join and listing what failed - never guessed.
ALIASES = {
    "manchester city": "man city",
    "manchester united": "man united",
    "newcastle united": "newcastle",
    "nottingham forest": "nottm forest",
    "wolverhampton wanderers": "wolves",
    "tottenham": "tottenham",
    "sheffield united": "sheffield united",
    "west bromwich albion": "west brom",
    "queens park rangers": "qpr",
    "paris saint germain": "paris sg",
    "borussia mgladbach": "mgladbach",
    "borussia dortmund": "dortmund",
    "bayer leverkusen": "leverkusen",
    "rasenballsport leipzig": "rb leipzig",
    "fc heidenheim": "heidenheim",
    "mainz 05": "mainz",
    "vfb stuttgart": "stuttgart",
    "eintracht frankfurt": "ein frankfurt",
    "fc cologne": "fc koln",
    "hertha berlin": "hertha",
    "real betis": "betis",
    "atletico madrid": "ath madrid",
    "athletic club": "ath bilbao",
    "real sociedad": "sociedad",
    "espanyol": "espanol",
    "celta vigo": "celta",
    "deportivo alaves": "alaves",
    "real valladolid": "valladolid",
    "rayo vallecano": "vallecano",
    "ac milan": "milan",
    "internazionale": "inter",
    "hellas verona": "verona",
    "clermont foot": "clermont",
    "saint etienne": "st etienne",
}

_STRIP = re.compile(r"[^a-z0-9 ]")


def norm(name):
    n = _STRIP.sub("", (name or "").lower().strip())
    n = re.sub(r"\s+", " ", n)
    return ALIASES.get(n, n)


def odds_index(league, season):
    """(date, home, away) -> odds row, for joining onto Understat fixtures."""
    idx = {}
    for r in odds_rows(league, season):
        try:
            d = parse_fd_date(r["Date"])
        except ValueError:
            continue
        idx[(d, norm(r["HomeTeam"]), norm(r["AwayTeam"]))] = r
    return idx


def joined(league, season):
    """Understat fixtures with pre-match odds attached.

    Returns (matched, unmatched). Kick-off dates can differ by a day between
    the two sources (timezone / late kick-offs), so the join tries +/-1 day.
    Unmatched fixtures are RETURNED, never silently dropped - a join that
    quietly loses fixtures would bias the sample in ways nothing downstream
    could detect.
    """
    idx = odds_index(league, season)
    matched, unmatched = [], []
    for m in league_fixtures(league, season):
        if not m.get("isResult"):
            continue
        d = dt.datetime.strptime(m["datetime"], "%Y-%m-%d %H:%M:%S").date()
        h, a = norm(m["h"]["title"]), norm(m["a"]["title"])
        row = None
        for off in (0, -1, 1):
            row = idx.get((d + dt.timedelta(days=off), h, a))
            if row:
                break
        if row is None:
            unmatched.append((str(d), h, a))
            continue
        prices = best_prematch(row)
        if prices is None:
            unmatched.append((str(d), h, a, "no usable odds"))
            continue
        matched.append({"match_id": m["id"], "date": d,
                        "home": m["h"]["title"], "away": m["a"]["title"],
                        "goals_h": int(m["goals"]["h"]), "goals_a": int(m["goals"]["a"]),
                        "odds_h": prices[0], "odds_d": prices[1], "odds_a": prices[2]})
    return matched, unmatched


def best_prematch(row):
    """Decimal home/draw/away from the most reliable column set present.

    Preference order: market average (AvgH) -> Pinnacle (PSH, sharpest single
    book) -> Bet365. Older seasons carry only some of these.
    """
    for h, d, a in (("AvgH", "AvgD", "AvgA"), ("PSH", "PSD", "PSA"),
                    ("BbAvH", "BbAvD", "BbAvA"), ("B365H", "B365D", "B365A")):
        try:
            vals = (float(row[h]), float(row[d]), float(row[a]))
        except (KeyError, TypeError, ValueError):
            continue
        if all(v > 1.0 for v in vals):
            return vals
    return None
