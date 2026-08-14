"""API-Football adapter. Every empirically-established feed detail lives here:
endpoint paths, field names, market filtering, statistics parsing, rate-limit
handling, and pre-match favourite resolution.

The one behaviour that must not regress: API-Football returns rate-limit errors
INSIDE a 200 response body (`errors.rateLimit`) rather than as an HTTP status,
so a naive client reads a throttled stats call as an empty response - which the
rest of the system would read as "zero shots", not "unknown". ApiClient.get
detects it, backs off, and retries.
"""
import time
import requests

from . import config


def norm(s):
    """Lower-case, alphanumerics only. Used for fuzzy name/market matching."""
    return "".join(c for c in str(s).lower() if c.isalnum())


def is_ft_market(name):
    n = norm(name)
    return (not any(b in n for b in config.NOT_FT)) and n in config.FT_MARKETS


def is_double_chance(name):
    return norm(name) in config.DOUBLE_CHANCE


def dc_key(value):
    """Normalise a double-chance outcome to '1X' (home/draw), 'X2' (draw/away)
    or '12' (home/away). Handles both 'Home/Draw' and '1X' style feeds."""
    n = norm(value)
    has_h = "home" in n or "1" in n
    has_a = "away" in n or "2" in n
    has_d = "draw" in n or "x" in n
    if has_h and has_d and not has_a:
        return "1X"
    if has_d and has_a and not has_h:
        return "X2"
    if has_h and has_a and not has_d:
        return "12"
    return None


class ApiClient:
    """Paced, rate-limit-aware HTTP client for one API key.

    PACING keeps a minimum gap between calls so a burst (e.g. the first poll of
    the day, when every fixture needs a pre-match odds lookup) is spread out
    rather than fired at once. BACKOFF handles the in-body rate-limit error.
    """

    def __init__(self, key=None, base=None, req_per_min=None, max_retry=3):
        self.key = key if key is not None else config.API_KEY
        self.base = base or config.API_BASE
        self.session = requests.Session()
        self.session.headers.update({"x-apisports-key": self.key or ""})
        self.gap = 60.0 / max(req_per_min or config.REQ_PER_MIN, 1.0)
        self.max_retry = max_retry
        self._last = 0.0
        self.reqs = 0            # total requests this run (incl. retries)
        self.calls = 0
        self.throttled = 0.0     # seconds spent waiting on the pacer
        self.retries = 0         # rate-limit backoff events

    def get(self, path, **params):
        for attempt in range(self.max_retry):
            wait = self.gap - (time.time() - self._last)
            if wait > 0:
                self.throttled += wait
                time.sleep(wait)
            self._last = time.time()
            self.calls += 1
            self.reqs += 1
            try:
                r = self.session.get(self.base + path, params=params, timeout=20)
                r.raise_for_status()
                body = r.json()
            except Exception as e:
                print("  ! %s failed: %s" % (path, e), flush=True)
                return []
            errs = body.get("errors") or {}
            if isinstance(errs, dict) and "rateLimit" in errs:
                self.retries += 1
                back = 8 * (attempt + 1)
                print("  ~ rate limited, backing off %ds (attempt %d/%d)"
                      % (back, attempt + 1, self.max_retry), flush=True)
                time.sleep(back)
                continue
            if errs:
                print("  ! API errors:", errs, flush=True)
            return body.get("response", [])
        print("  ! gave up on %s after %d rate-limited attempts"
              % (path, self.max_retry), flush=True)
        return []


# --- statistics -------------------------------------------------------------
def parse_stats(rows, team_id):
    """Pull the four metrics for one team. Returns (values, xg_seen).

    A missing stat stays None - NEVER 0 - so "no shot data" is distinguishable
    from "zero shots". xG key naming varies across competitions, so it is
    matched loosely and its presence reported: a silently-absent xG would
    quietly turn a 4-condition rule into a 3-condition one.
    """
    out = {"xg": None, "shots": None, "sot": None, "box": None}
    xg_seen = False
    for row in rows:
        if (row.get("team") or {}).get("id") != team_id:
            continue
        for st in row.get("statistics", []):
            t, v = norm(st.get("type")), st.get("value")
            if v is None:
                continue
            try:
                if "expectedgoal" in t or t == "xg":
                    out["xg"] = float(v)
                    xg_seen = True
                elif t == "totalshots":
                    out["shots"] = int(v)
                elif t == "shotsongoal":
                    out["sot"] = int(v)
                elif t == "shotsinsidebox":
                    out["box"] = int(v)
            except (TypeError, ValueError):
                pass
    return out, xg_seen


# --- odds -------------------------------------------------------------------
def live_prices(api):
    """Live full-time-result prices per fixture, keyed by outcome name.

    NOTE (unverified): whitelisted FT markets are merged into one dict per
    fixture, last write wins. One observed price looked implausible for the
    favourite and may have been the draw. Verify against a raw /odds/live dump
    before fully trusting the price band.
    """
    out, susp, blocked = {}, 0, 0
    for row in api.get("/odds/live"):
        st = row.get("status") or {}
        if st.get("blocked") or st.get("stopped") or st.get("finished"):
            blocked += 1
            continue
        fid, d = str((row.get("fixture") or {}).get("id")), {}
        for bet in row.get("odds", []):
            name = bet.get("name")
            ft, dc = is_ft_market(name), is_double_chance(name)
            if not (ft or dc):
                continue
            for v in bet.get("values", []):
                if v.get("suspended"):
                    susp += 1
                    continue
                try:
                    odd = float(v.get("odd"))
                except (TypeError, ValueError):
                    continue
                if ft:
                    # Home / Away / Draw
                    d[str(v.get("value"))] = odd
                else:
                    # 1X / X2 / 12 (kept under distinct keys, no collision)
                    key = dc_key(v.get("value"))
                    if key:
                        d[key] = odd
        if d:
            out[fid] = d
    print("  odds: %d priced (%d blocked, %d suspended skipped)"
          % (len(out), blocked, susp), flush=True)
    return out


def signal_price(fx_prices, side, behind):
    """The live price the strategy actually trades, given the favourite's side
    and whether it is currently behind.

    - Favourite level (not behind): back it to WIN -> its live win odds.
    - Favourite behind: back the DOUBLE CHANCE (win or draw) -> 1X for a home
      favourite, X2 for an away one. Taken live if the feed offers it, else
      DERIVED by combining the two winning legs' implied probabilities:

          1/dc_odds = 1/fav_win_odds + 1/draw_odds
          dc_odds   = 1 / (1/fav_win_odds + 1/draw_odds)

      i.e. 1X from Home+Draw, X2 from Away+Draw. This carries the same 1x2
      margin as the outright prices, so it reproduces the feed's own live DC
      closely (verified to ~1% against /odds/live). It is still an estimate and
      is flagged as derived.

    Returns {price, market, kind, derived}. price is None when nothing is
    available - the caller then SKIPS the price condition rather than failing it.
    """
    fx = fx_prices or {}
    if not behind:
        p = fx.get("Home" if side == "home" else "Away")
        return {"price": p, "market": "win", "kind": "win", "derived": False}

    key = "1X" if side == "home" else "X2"
    live = fx.get(key)
    if live is not None:
        return {"price": live, "market": key, "kind": "dc", "derived": False}

    fav_win = fx.get("Home" if side == "home" else "Away")  # the favourite's win odds
    draw = fx.get("Draw")
    if fav_win and draw and fav_win > 0 and draw > 0:
        denom = 1.0 / fav_win + 1.0 / draw
        if denom > 0:
            return {"price": 1.0 / denom, "market": key, "kind": "dc",
                    "derived": True}
    return {"price": None, "market": key, "kind": "dc", "derived": False}


def prematch_favourite(api, fid, cache):
    """(side, price) for the shorter-priced pre-match team, or None. Cached per
    fixture - pre-match odds do not change once the match is live."""
    if fid in cache:
        return cache[fid]
    bh = ba = None
    for row in api.get("/odds", fixture=fid):
        for bm in row.get("bookmakers", []):
            for bet in bm.get("bets", []):
                if not is_ft_market(bet.get("name")):
                    continue
                for v in bet.get("values", []):
                    try:
                        o = float(v.get("odd"))
                    except (TypeError, ValueError):
                        continue
                    if v.get("value") == "Home":
                        bh = o if bh is None else min(bh, o)
                    elif v.get("value") == "Away":
                        ba = o if ba is None else min(ba, o)
    if bh is None and ba is None:
        cache[fid] = None
    elif ba is None or (bh is not None and bh <= ba):
        cache[fid] = ("home", bh)
    else:
        cache[fid] = ("away", ba)
    return cache[fid]


# --- league resolution ------------------------------------------------------
CZ_COUNTRY = ("czechrepublic", "czechia", "czech")
CZ_NAME = ("czechliga", "chanceliga", "fortunaliga", "czechfirstleague",
           "firstleague", "prvniliga", "1liga")


def _resolve_czech(cat):
    """Czech top flight, robust to the feed renaming the country (Czechia) or
    the sponsor (Chance Liga, formerly Fortuna Liga). Prints what it saw and
    what it picked, so a wrong guess is visible rather than silent."""
    cands = [x for x in cat if any(a in norm(x[0]) for a in CZ_COUNTRY)]
    if not cands:
        print("  ..      no Czech competitions in the feed")
        return None
    print("  ..      Czech competitions returned by the feed:")
    for c, n, i, t in cands:
        print("            id=%-7s %-34s %s" % (i, n, t))
    for c, n, i, t in cands:
        if str(t).lower() == "league" and any(a in norm(n) for a in CZ_NAME):
            print("  ..      picked id=%s (%s) - check this is the top flight"
                  % (i, n))
            return i
    print("  ..      no top-flight name matched; left MISSING")
    return None


def resolve_leagues(api):
    """Map config.LEAGUES to feed ids. Exact match, then substring, then the
    Czech aliaser, then PINNED_IDS as a last resort."""
    rows = api.get("/leagues")
    if not rows:
        print("Could not load leagues - running with NO filter.")
        return set()
    cat = [((r.get("country") or {}).get("name") or "",
            (r.get("league") or {}).get("name") or "",
            (r.get("league") or {}).get("id"),
            (r.get("league") or {}).get("type") or "") for r in rows]
    ids = set()
    for country, name in config.LEAGUES:
        hit = next((i for c, n, i, t in cat
                    if norm(c) == norm(country) and norm(n) == norm(name)), None)
        if hit is None:
            hit = next((i for c, n, i, t in cat if norm(c) == norm(country)
                        and (norm(name) in norm(n) or norm(n) in norm(name))), None)
        if hit is None and norm(country) in CZ_COUNTRY:
            hit = _resolve_czech(cat)
        if hit is None:
            hit = config.PINNED_IDS.get((country, name))
            if hit is not None:
                print("  PIN     %-16s %-32s id=%s (name match failed)"
                      % (country, name, hit))
        if hit:
            ids.add(hit)
            print("  OK      %-16s %-32s id=%s" % (country, name, hit))
        else:
            print("  MISSING %s: %s" % (country, name))
    print("\n%d/%d competitions resolved.\n" % (len(ids), len(config.LEAGUES)),
          flush=True)
    return ids


def show_stats(api):
    """--stats: dump every statistic type the feed returns for one live match,
    so the xG-presence question can be settled by inspection."""
    for fx in api.get("/fixtures", live="all")[:12]:
        fid = fx["fixture"]["id"]
        rows = api.get("/fixtures/statistics", fixture=fid)
        if not rows:
            continue
        print("fixture %s  %s v %s" % (fid, fx["teams"]["home"]["name"],
                                       fx["teams"]["away"]["name"]))
        for st in rows[0].get("statistics", []):
            print("   %-28s %s" % (st.get("type"), st.get("value")))
        return
    print("no live fixture with statistics found")
