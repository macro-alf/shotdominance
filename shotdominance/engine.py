"""The monitor engine. One Monitor object owns all cross-poll state (history,
judged checkpoints, open exposure, acknowledgements, bets, telegram offset) -
replacing the module-level globals and monkeypatched functions of the old
seven-file chain.

The console output format is deliberately identical to the old build so that
review.py keeps parsing it, with one addition: the pre-match price is now
printed (pm=...) so the effect of the 1.30-2.25 gate is measurable.
"""
import time

from . import apifootball, blotter, config, ledger, rules, sizing, state


class Monitor:
    def __init__(self, api, tg, league_ids):
        self.api = api
        self.tg = tg
        self.league_ids = league_ids

        # per-fixture working state
        self.history = {}        # fid -> [Snapshot, ...]
        self.done = {}           # fid -> set(judged checkpoints)
        self.open_pos = {}       # fid -> staked amount (exposure)
        self.prematch = {}       # fid -> (side, price) | None
        self.price_cache = {}    # fid -> (timestamp, odds dict) for carry-forward
        self.stats_cache = {}    # fid -> {'f':(ts,stat), 'o':(ts,stat)} carry-forward
        self.best_conv = {}      # fid -> highest conviction already alerted
        self.last_conv = {}      # fid -> last conviction, for adaptive polling
        self.skipped = 0         # fixtures skipped this poll as too dull
        # OBSERVABILITY. Three times in a week the answer to "why did nothing
        # fire?" was a silent data loss nobody was counting: an API timeout that
        # broke a momentum window (Aris Thessalonikis 2026-09-19, 21 shots to 2,
        # lost cp60 and cp65), a fixture the feed never described at all
        # (Fenerbahce 2026-09-15, vol 0/0 for ninety minutes), and a bulk odds
        # outage that blinded every watched fixture at once. Each is now
        # counted for the day and printed, so the cost is visible instead of
        # being reconstructed from the log afterwards.
        self.lost = dict(no_window=0, no_stats=0, no_price=0, feed_fail=0)
        self.pens = {}           # fid -> {'at': minute last checked, 'seen': set(key),
                                 #         'sub': {team_id: {metric: amount}}}
        self._now = 0.0

        # cross-poll / telegram state (persisted)
        self.acked = set()       # fids with a logged bet -> suppress alerts
        self.muted = set()       # fids Alf replied "ignore" to -> suppress alerts
        self.alerted_cp = set()  # "fid:cp" already alerted -> one alert per checkpoint
        self.msg2fid = {}        # telegram message_id -> fid
        self.awaiting = {}       # chat_id -> fid (waiting for stake & price)
        self.bets = []           # blotter rows
        self.blocks = []         # blocked-signal ledger rows
        self.last_alert = {}     # fid -> context dict for record_bet
        self.offset = 0          # telegram getUpdates cursor
        self.xg_seen = False
        self.feed_bad = 0        # consecutive polls the API refused
        self.feed_alerted = 0.0  # when we last said so on Telegram
        self.polls = 0           # polls this run, for the periodic quota check
        self.quota_warned = False
        self.quota_frac = 0.0    # day's allowance used, gates SLOW_POLL
        self.poll_seconds = config.POLL_SECONDS   # monitor.py sleeps by this

    # --- persistence --------------------------------------------------------
    def save(self):
        state.save(config.STATE_PATH, {
            "acked": sorted(self.acked), "muted": sorted(self.muted),
            "alerted_cp": sorted(self.alerted_cp),
            "msg2fid": self.msg2fid,
            "await": self.awaiting, "bets": self.bets, "offset": self.offset,
            # PERSIST THE ALERT CONTEXT. It used to live only in memory, so a
            # restart between an alert and Alf's reply produced a blotter row
            # with no match, no side and no back - and settle_bet grades the
            # bet from `side`, so it would have been settled as the WRONG TEAM.
            # Happened for real on 2026-09-20 (Wolves 0-0 West Brom, 1563177,
            # 1502 @ 2.10) and the row had to be repaired by hand.
            "last_alert": self.last_alert})

    def load(self):
        d = state.load(config.STATE_PATH)
        if not d:
            return
        self.acked.update(d.get("acked", []))
        self.muted.update(d.get("muted", []))
        self.alerted_cp.update(d.get("alerted_cp", []))
        self.msg2fid.update({str(k): v for k, v in (d.get("msg2fid") or {}).items()})
        self.awaiting.update(d.get("await") or {})
        self.bets.extend(d.get("bets") or [])
        self.offset = d.get("offset", 0)
        self.last_alert.update(d.get("last_alert") or {})
        print("  state restored: %d acked, %d bets"
              % (len(self.acked), len(self.bets)), flush=True)

    # --- telegram inbound ---------------------------------------------------
    def receive(self):
        """Handle replies. 'bet done' on an alert -> ask for stake and price;
        two numbers in the follow-up -> log the bet."""
        import re
        for upd in self.tg.updates(self.offset):
            self.offset = max(self.offset, upd.get("update_id", 0))
            msg = upd.get("message") or {}
            text = (msg.get("text") or "").strip()
            chat = str((msg.get("chat") or {}).get("id"))
            reply_to = str(((msg.get("reply_to_message") or {}).get("message_id")) or "")
            if not text:
                continue

            # PRICE QUERY - reply to an alert with ONE number and get the stake
            # that price implies. The API serves bookmaker quotes; the exchange
            # price is better and only Alf knows it, so the sizing has to be
            # askable after the fact. Checked BEFORE stage 2 because a single
            # number is never a valid "stake and price" pair.
            if reply_to in self.msg2fid:
                nums = re.findall(r"\d+(?:[.,]\d+)?", text.replace(",", "."))
                if len(nums) == 1 and "bet done" not in text.lower():
                    self.quote(chat, self.msg2fid[reply_to], float(nums[0]))
                    continue

            # stage 2 - we asked for stake and price
            if chat in self.awaiting:
                nums = re.findall(r"\d+(?:[.,]\d+)?", text.replace(",", "."))
                if len(nums) >= 2:
                    fid = self.awaiting.pop(chat)
                    self.record_bet(fid, float(nums[0]), float(nums[1]))
                else:
                    self.tg.send("Need two numbers: stake then price, e.g. `650 2.60`")
                continue

            # IGNORE - silence a fixture without recording a bet. Alerts now
            # repeat at every checkpoint (see _fire_decision), so there has to
            # be a way to say "seen it, not betting" that is not "bet done".
            if text.lower().strip() in ("ignore", "ignored", "skip") or                     text.lower().startswith("ignore"):
                fid = self.msg2fid.get(reply_to)
                if not fid:
                    self.tg.send("Reply *to the alert message itself* so I know "
                                 "which match to ignore. Nothing changed.")
                    continue
                self.muted.add(fid)
                self.tg.send("Ignored. No further alerts for this match, and no "
                             "bet recorded.")
                continue

            # stage 1 - acknowledgement on a specific alert
            if "bet done" in text.lower():
                fid = self.msg2fid.get(reply_to)
                if not fid:
                    self.tg.send("Reply *to the alert message itself* so I know "
                                 "which match. Nothing recorded.")
                    continue
                self.acked.add(fid)
                self.awaiting[chat] = fid
                self.tg.send("Recorded as bet. Now reply with stake and price, "
                             "two numbers: e.g. `650 2.60`")
        self.save()

    def quote(self, chat, fid, price):
        """Re-size an existing alert at a price Alf actually found.

        The alert's own stake is computed from API-Football's BOOKMAKER quote,
        which carries overround and is routinely beatable on an exchange. This
        lets him reply to the alert with the real number and get the stake that
        price implies, at the SAME conviction. Nothing is recorded - it is a
        calculator, not a bet.
        """
        ctx = self.last_alert.get(fid)
        if not ctx:
            self.tg.send("That alert is no longer in memory, so I cannot size "
                         "it. Reply to a more recent one.")
            return
        if not (1.01 <= price <= 1000.0):
            self.tg.send("Give me a decimal price above 1.01, e.g. `1.95`.")
            return
        # exclude this fixture's own reserved exposure so re-quoting the same
        # alert twice does not eat its own room
        open_total = sum(v for k, v in self.open_pos.items() if k != fid)
        sz = sizing.size(price, ctx["conv"], open_total)
        quoted = ctx.get("price")
        delta = ("" if quoted is None else
                 "  (API quoted %.2f, you found %+.1f%%)"
                 % (quoted, 100.0 * (price / quoted - 1.0)))
        lines = ["SIZING at %.2f%s" % (price, delta),
                 ctx["label"], "conviction %.0f/100" % ctx["conv"], "",
                 "Stake: %.0f EUR   [x%.2f on conviction, bound by %s]"
                 % (sz["stake"], sz["mult"], sz["bound"]),
                 "  target-win base %.0f, %.0f%%-Kelly cap %.0f"
                 % (sz["base"], config.KELLY_FRAC * 100, sz["kelly"]),
                 "  implied %.1f%% from the price, model assumes %.1f%%"
                 % (100.0 / price, 100.0 * sz["p"]),
                 "", "Edge is a model assumption, not a measured quantity."]
        if chat in self.awaiting:
            lines += ["", "(still waiting on `stake price` to log the bet)"]
        self.tg.send("\n".join(lines))
        print("   >>> QUOTE %s @ %.2f -> stake %.0f (conv %.0f)"
              % (ctx["label"], price, sz["stake"], ctx["conv"]), flush=True)

    # --- quote sanity -------------------------------------------------------
    def _sane_price(self, fid, price, label="", pm=None):
        """Reject a live quote that is implausibly SHORT for the pre-match price.

        v2. The previous version compared each quote to the last one, which a
        goal breaks and which let a bad first sighting become the reference.
        This compares the LEVEL to the pre-match price: no history, nothing to
        poison, and it works on the first quote a fixture ever shows.

        One-sided by design - see the measured table at config.QUOTE_MIN_RATIO.
        A drift to 20x on a dying match is real information; a quote at half the
        pre-match price on a side that is not winning is not.
        """
        if price is None or not config.QUOTE_SANITY:
            return price
        # A decimal price at or below 1.00 pays less than the stake back and
        # cannot exist. Four turned up in five weeks of logs (0.98, 0.98, 0.99,
        # 0.99) and were only caught by the ratio test because those fixtures
        # happened to be ~2.00 pre-match; on a 1.50 favourite 0.98 would be a
        # ratio of 0.65 and would have passed. Absolute, no calibration needed.
        if price <= 1.01:
            print("   ! %s: quote %.2f rejected - a decimal price at or below "
                  "1.01 cannot exist. Treated as NO PRICE."
                  % (label or fid, price), flush=True)
            return None
        if not pm or pm <= 0:
            return price
        if price < config.QUOTE_MIN_RATIO * pm:
            print("   ! %s: quote %.2f rejected - %.2f of a %.2f pre-match "
                  "(floor %.2f). Treated as NO PRICE; almost certainly another "
                  "market in the win slot."
                  % (label or fid, price, price / pm, pm,
                     config.QUOTE_MIN_RATIO * pm), flush=True)
            return None
        return price

    # --- blocked-signal ledger ----------------------------------------------
    def _record_block(self, fid, cp, ctx, blocked_by):
        """Record a checkpoint the gates refused, for later settlement.

        Only called where the EVIDENCE rule passed - a signal that failed on
        shots was never a candidate and would swamp the table. Keyed on
        (day, fixture, checkpoint) by the ledger, so the repeated evaluations
        inside an open grace window update one row rather than appending dozens.
        """
        if not config.BLOCKED_LEDGER:
            return
        row = ledger.new_block(fid, cp, ctx, blocked_by)
        key = ledger._key(row)
        for i, existing in enumerate(self.blocks):
            if ledger._key(existing) == key:
                row["status"] = existing.get("status", "open")
                row["final_score"] = existing.get("final_score", "")
                row["pnl_at_quote"] = existing.get("pnl_at_quote", "")
                self.blocks[i] = row
                break
        else:
            self.blocks.append(row)
        ledger.write(config.BLOCKED_LEDGER_PATH, self.blocks)

    # --- blotter ------------------------------------------------------------
    def record_bet(self, fid, stake, price):
        ctx = self.last_alert.get(fid) or {}
        if not ctx.get("label"):
            # Never write a bet we cannot identify: settle_bet decides which
            # side was backed from `side`/`back`, so a blind row settles as the
            # wrong team. One /fixtures call is far cheaper than a mis-settled
            # bet. See the note in save() for how this happened.
            print("   ! no alert context for %s - recovering it from the feed"
                  % fid, flush=True)
            try:
                rows = self.api.get("/fixtures", id=fid)
                fx = rows[0]
                t, g = fx.get("teams") or {}, fx.get("goals") or {}
                home, away = (t.get("home") or {}), (t.get("away") or {})
                pm = self.prematch.get(fid)
                side = pm[0] if pm else "home"
                fav = home if side == "home" else away
                ctx = dict(label="%s %s-%s %s" % (home.get("name"),
                                                  g.get("home"), g.get("away"),
                                                  away.get("name")),
                           league=((fx.get("league") or {}).get("name") or ""),
                           minute=(((fx.get("fixture") or {}).get("status")
                                    or {}).get("elapsed") or ""),
                           fav=fav.get("name"), side=side,
                           score="%s-%s" % (g.get("home"), g.get("away")),
                           market="win" if (g.get("home") == g.get("away"))
                                  else ("1X" if side == "home" else "X2"))
                self.last_alert[fid] = ctx
            except Exception as e:
                self.tg.send("Could not identify the fixture for that bet (%s). "
                             "It is logged but the row is incomplete - tell "
                             "Claude before it settles." % fid)
                print("   ! context recovery failed: %s" % e, flush=True)
        bet = blotter.new_bet(fid, ctx, stake, price)
        self.bets.append(bet)
        blotter.write(config.BLOTTER_PATH, self.bets)
        self.save()
        self.tg.send("Logged: %s, back %s, stake %.0f at %.2f. Settles at full "
                     "time." % (bet["match"] or fid, bet["back"], stake, price))
        print("   >>> BET LOGGED %s stake %.0f @ %.2f"
              % (bet["match"], stake, price), flush=True)

    def settle(self, live_ids):
        """Close out bets, and grade the blocked-signal ledger, once their
        fixture has left the live board and finished.

        Both tables settle from the SAME fixture fetch: a fixture that produced
        a bet usually produced several blocked checkpoints first, and paying for
        that lookup twice would be waste. Open rows in either table contribute
        their fixture id once.
        """
        pending = {}
        for b in self.bets:
            if b["status"] == "open" and str(b["fixture_id"]) not in live_ids:
                pending.setdefault(str(b["fixture_id"]), None)
        for r in self.blocks:
            if r.get("status") == "open" and str(r["fixture_id"]) not in live_ids:
                pending.setdefault(str(r["fixture_id"]), None)
        if not pending:
            return

        for fid in list(pending):
            rows = self.api.get("/fixtures", id=fid)
            if not rows:
                continue
            fx = rows[0]
            st = ((fx.get("fixture") or {}).get("status") or {}).get("short")
            if st not in ("FT", "AET", "PEN"):
                continue
            g, t = fx.get("goals") or {}, fx.get("teams") or {}
            pending[fid] = (int(g.get("home") or 0), int(g.get("away") or 0),
                            (t.get("home") or {}).get("name"))

        changed = False
        for b in self.bets:
            got = pending.get(str(b["fixture_id"]))
            if b["status"] != "open" or not got:
                continue
            hs, as_, home = got
            blotter.settle_bet(b, home, hs, as_)
            changed = True
            tot = sum(float(x["pnl"]) for x in self.bets
                      if x["status"] in ("won", "lost"))
            self.tg.send("Settled: %s %d-%d. %s %+.2f EUR.\nRunning P&L: %+.2f "
                         "EUR over %d bets."
                         % (b["match"], hs, as_, b["status"].upper(), b["pnl"],
                            tot, sum(1 for x in self.bets if x["status"] != "open")))
            print("   settled %s -> %s %+.2f"
                  % (b["match"], b["status"], b["pnl"]), flush=True)
        if changed:
            blotter.write(config.BLOTTER_PATH, self.bets)

        graded = False
        for r in self.blocks:
            got = pending.get(str(r["fixture_id"]))
            if r.get("status") != "open" or not got:
                continue
            hs, as_, home = got
            ledger.settle_block(r, home, hs, as_)
            graded = True
            print("   ledger: cp%s %s -> %s (refused at %s, needed %s)"
                  % (r["checkpoint"], r["match"], r["status"],
                     r["live_price"] or "n/a", r["need"]), flush=True)
        if graded:
            ledger.write(config.BLOCKED_LEDGER_PATH, self.blocks)
        if changed or graded:
            self.save()

    # --- output helpers -----------------------------------------------------
    @staticmethod
    def brief(fav, opp, th):
        """value[required]/opponent for the four metrics."""
        out = []
        for k in config.KEYS:
            v, o, n = fav.get(k), opp.get(k), th[k]
            if v is None:
                out.append("%s=n/a" % k)
                continue
            fmt = (lambda x: "%.2f" % x) if k == "xg" else (
                lambda x: "%d" % x if float(x) == int(x) else "%.1f" % x)
            out.append("%s=%s[%s]/%s" % (k, fmt(v), fmt(n),
                                         "?" if o is None else fmt(o)))
        return " ".join(out)

    @staticmethod
    def alert_text(ctx, ev, sz, price, pm):
        if ctx.get("kind") == "dc":
            back = ("Back: %s win or draw  (double chance %s%s)"
                    % (ctx["fav"], ctx.get("market", "DC"),
                       ", derived odds" if ctx.get("derived") else ""))
            price_tag = "double chance %s" % ctx.get("market", "DC")
        else:
            back = "Back: %s to win" % ctx["fav"]
            price_tag = "win"
        lines = ["SIGNAL  conviction %.0f/100" % ev.conv,
                 ctx["label"], "%s - %d'" % (ctx["league"], ctx["minute"]), "",
                 back]
        need = ctx.get("need")
        winp = ctx.get("winp")
        edge_line = ("MINIMUM PRICE FOR AN EDGE: %.2f   (%s, %d', pre-match %.2f, "
                     "P(win) %.0f%%)"
                     % (need, ctx.get("state", "?"), ctx["minute"],
                        ctx.get("pm", 0.0), 100 * winp)) if need else ""
        if price is None:
            lines += ["Price: NOT AVAILABLE - check manually"]
            if edge_line:
                lines += ["  " + edge_line,
                          "  Anything at or above that price is worth taking; "
                          "below it, skip."]
            lines += ["", "Stake: cannot size without a price"]
        else:
            band = "" if config.PRICE_FLOOR <= price <= config.PRICE_CEIL else (
                "  ** BOOKMAKER QUOTE IS OUTSIDE %.2f-%.2f - the stake below is "
                "sized at the nearest in-band price. BEAT THIS NUMBER on the "
                "exchange or skip it. **" % (config.PRICE_FLOOR, config.PRICE_CEIL))
            lines += ["Price: %.2f  (%s; pre-match fav %.2f)"
                      % (price, price_tag, pm)]
            if edge_line:
                lines += ["  " + edge_line]
            sb = ctx.get("short_by") or 0.0
            if sb > 0:
                lines += ["  ** THIS PRICE IS %.2f SHORT OF THE MINIMUM (%.2f "
                          "available, %.2f required). Fired inside the %.2f "
                          "tolerance - there is NO modelled edge at this price. "
                          "Beat %.2f on the exchange or skip it. **"
                          % (sb, price, need, config.EDGE_TOLERANCE, need)]
            if band:
                lines += [band]
            lines += ["",
                      "Stake: %.0f EUR   [x%.2f on conviction, bound by %s]"
                      % (sz["stake"], sz["mult"], sz["bound"]),
                      "  target-win base %.0f, half-Kelly cap %.0f"
                      % (sz["base"], sz["kelly"])]
        time_note = ("  (time left %.0f%%, x%.2f)" % (ev.s_time, ev.time_mult)
                     if ev.time_mult != 1.0 else "")
        lines += ["", "Basis: %s" % ev.basis,
                  "Scores: volume %.0f | momentum %.0f | dominance %.0f%s"
                  % (ev.s_vol, ev.s_mom, ev.s_dom, time_note),
                  "", "Cumulative (value/bar, opp as % of ours)",
                  "  " + "\n  ".join(ev.vol_det),
                  "", Monitor._window_line(ctx, ev),
                  "  " + "\n  ".join(ev.mom_det)]
        for x in ev.extra:
            lines += ["", x]
        lines += ["", "Reply TO THIS MESSAGE with:",
                  "  a price (e.g. `1.95`) -> stake at the odds YOU can get",
                  "  'bet done'            -> stop repeats, then log stake+price",
                  "Edge is a model assumption, not a measured quantity."]
        return "\n".join(lines)

    @staticmethod
    def _window_line(ctx, ev):
        """Header for the momentum block: exactly which minutes it covers.

        "Last 30 min" is not checkable from the message. The span is, and a
        shortened one has to announce itself - an alert that quietly measured 22
        minutes while looking like 30 is the same failure as one that measured
        the whole match (Sion v Ajax, 2026-08-20).
        """
        now = ctx["minute"]
        frm = now - ev.win_min
        if ev.win_min >= config.WINDOW:
            return ("Momentum window: %d' -> %d'  (%d min, full - real stats)"
                    % (frm, now, ev.win_min))
        return ("Momentum window: %d' -> %d'  (%d min, SHORTENED - no stats "
                "available before %d'; bar scaled to %d min)"
                % (frm, now, ev.win_min, frm, ev.win_min))

    # --- stats carry-forward ------------------------------------------------
    @staticmethod
    def _empty(stat):
        return all(stat.get(k) is None for k in config.KEYS)

    def _carry_stats(self, fid, fstat, ostat):
        """Substitute the last non-empty stats for a fixture when a poll returns
        an empty set (rate-limited / feed gap), so it is not read as 0 shots.
        Favourite and opponent are carried independently. Returns (f, o, carried).
        """
        lg = self.stats_cache.get(fid, {})
        carried = False

        def resolve(cur, key):
            nonlocal carried
            if not self._empty(cur):
                lg[key] = (self._now, dict(cur))     # remember the fresh reading
                return cur
            prev = lg.get(key)
            if prev and (self._now - prev[0]) <= config.STATS_CARRY_TTL:
                carried = True
                return dict(prev[1])
            return cur

        f, o = resolve(fstat, "f"), resolve(ostat, "o")
        self.stats_cache[fid] = lg
        return f, o, carried

    # --- adaptive polling ---------------------------------------------------
    def _due_for_poll(self, fid, minute):
        """Whether this fixture is worth a /fixtures/statistics call this cycle.

        Decided from the minute alone, which the live-fixtures list already
        gave us, so a skip costs nothing. Never skips inside a checkpoint's
        grace window: that guarantees no checkpoint is missed AND that every
        fixture's conviction is refreshed at least once per checkpoint, so
        nothing gets stranded in the slow tier after it improves.
        """
        if not config.SLOW_POLL:
            return True
        # A RESCUE, not the default. Below SLOW_POLL_FROM_QUOTA of the day's
        # allowance there is nothing to save and every watched fixture is
        # measured every cycle; see the block at config.SLOW_POLL_FROM_QUOTA.
        if self.quota_frac < config.SLOW_POLL_FROM_QUOTA:
            return True
        conv = self.last_conv.get(fid)
        if conv is None:
            return True                      # never measured - must look
        for cp in config.CHECKPOINTS:
            if cp <= minute <= cp + config.CHECKPOINT_GRACE:
                return True                  # at or inside a checkpoint window
        if conv < config.SLOW_POLL_LOW_CONV:
            every = config.SLOW_POLL_LOW_EVERY
        elif conv < config.SLOW_POLL_MID_CONV:
            every = config.SLOW_POLL_MID_EVERY
        else:
            return True
        return (self.polls % every) == 0

    # --- penalties ----------------------------------------------------------
    @staticmethod
    def _penalty_cost(scored):
        """What one penalty attempt adds to the feed's numbers, to be removed."""
        return {"shots": 1.0, "box": 1.0, "xg": config.PENALTY_XG,
                "sot": 1.0 if (scored or config.PENALTY_MISSED_ON_TARGET) else 0.0}

    def _strip_penalties(self, fid, minute, fstat, ostat, fav_id, opp_id,
                         label_hint=("", "")):
        """Remove penalty attempts from both sides' cumulative stats.

        The subtraction is applied to the RAW feed reading every poll, so it is
        idempotent - there is no way to double-subtract by running twice.
        Discovery costs one /fixtures/events call, refreshed every
        PENALTY_REFRESH_MIN match-minutes rather than every poll.

        A penalty found LATE is also retro-subtracted from any snapshot already
        recorded at or after its minute, so the momentum window differences a
        consistent series. Without that, a baseline taken before discovery would
        still contain the penalty while the current reading no longer did, and
        the delta would under-report momentum by the penalty's worth.
        """
        if not config.STRIP_PENALTIES:
            return fstat, ostat

        rec = self.pens.setdefault(fid, {"at": None, "seen": set(), "sub": {}})
        stale = rec["at"] is None or (minute - rec["at"]) >= config.PENALTY_REFRESH_MIN
        if stale and minute <= config.PENALTY_STOP_MIN:
            try:
                found = apifootball.penalties(self.api, fid)
                rec["at"] = minute
                for p in found:
                    if p["key"] in rec["seen"]:
                        continue
                    rec["seen"].add(p["key"])
                    cost = self._penalty_cost(p["scored"])
                    tot = rec["sub"].setdefault(p["team"], {})
                    for k, v in cost.items():
                        tot[k] = tot.get(k, 0.0) + v
                    side = "fav" if p["team"] == fav_id else (
                        "opp" if p["team"] == opp_id else None)
                    if side:
                        self._retro_strip(fid, p["minute"], side, cost)
                    who = label_hint[0] if p["team"] == fav_id else label_hint[1]
                    print("   PENALTY %s %s %s' - stripping %s"
                          % ("scored" if p["scored"] else "missed", who or p["team"],
                             p["minute"],
                             ", ".join("%s-%g" % (k, v) for k, v in sorted(cost.items()) if v)),
                          flush=True)
            except Exception as e:                   # never let this stop a poll
                print("   ! penalty lookup failed: %s" % e, flush=True)

        return (self._less(fstat, rec["sub"].get(fav_id)),
                self._less(ostat, rec["sub"].get(opp_id)))

    @staticmethod
    def _less(stat, sub):
        """stat minus sub, leaving None as None and never going below zero."""
        if not sub:
            return stat
        out = dict(stat)
        for k, v in sub.items():
            if out.get(k) is None:
                continue
            out[k] = max(0.0, out[k] - v) if k == "xg" else max(0, int(round(out[k] - v)))
        return out

    def _retro_strip(self, fid, pen_minute, side, cost):
        """Apply a newly-found penalty to snapshots already recorded at/after it.

        `side` is "fav" or "opp": a Snapshot stores the two teams positionally
        with no ids, so the caller resolves which one the penalty belongs to.
        """
        for snap in self.history.get(fid, []):
            if snap.minute < pen_minute:
                continue
            if side == "fav":
                snap.fav.update(self._less(snap.fav, cost))
            else:
                snap.opp.update(self._less(snap.opp, cost))

    # --- firing policy ------------------------------------------------------
    def _fire_decision(self, fid, conv):
        """Whether an eligible signal should actually be sent. Applies the
        conviction floor only. Returns (fire, reason_when_not_firing).

        CHANGED 2026-09-07 on Alf's instruction: a signal now re-fires at EVERY
        checkpoint it is still valid at, and is silenced only by replying
        "bet done" or "ignore" to the alert on Telegram. The old rule repeated
        only on a NEW conviction high, which meant a fixture that alerted at 90
        and then sat at 85 went silent for the rest of the match even though 85
        is a strong signal -- and if the first alert was missed there was no
        second chance. Suppression is now Alf's decision, not the engine's.

        NOTE this makes the exposure fix below load-bearing: without it a
        repeating alert eats its own reserved room and decays 2000 -> 1000 -> 0.
        """
        if conv < config.CONV_FIRE_MIN:
            # one decimal, not zero: %.0f printed "conviction 50 below 50 floor"
            # for a true 49.6 (Mainz, 2026-08-29 cp75), which reads as a bug
            return False, ("no signal: conviction %.1f below %.0f floor"
                           % (conv, config.CONV_FIRE_MIN))
        return True, None

    # --- one poll -----------------------------------------------------------
    def poll(self):
        self.receive()
        self._now = time.time()
        prices = apifootball.live_prices(self.api)
        # remember each fixture's latest odds so a later blocked poll can reuse it
        for pid, pd in prices.items():
            self.price_cache[pid] = (self._now, pd)
        fixtures = self.api.get("/fixtures", live="all")
        watched = 0
        calls_before = self.api.calls
        t0 = time.time()

        for fx in fixtures:
            try:
                self._poll_fixture(fx, prices)
                if self._last_watched:
                    watched += 1
            except Exception as e:
                print("  ! fixture error:", e, flush=True)

        live = {str((f.get("fixture") or {}).get("id")) for f in fixtures}
        self.settle(live)
        for d in (self.history, self.done, self.open_pos, self.price_cache,
                  self.stats_cache, self.best_conv):
            for k in [k for k in d if k not in live]:
                del d[k]

        self._feed_health()
        self._quota_guard()

        print("   pacing: %d calls in %.0fs, %.0fs waiting, %d retries"
              % (self.api.calls - calls_before, time.time() - t0,
                 self.api.throttled, self.api.retries), flush=True)
        print("poll: %d live, %d watched, %d requests total%s%s"
              % (len(fixtures), watched, self.api.reqs,
                 "" if not self.skipped else "   [%d dull skipped]" % self.skipped,
                 "" if self.xg_seen else "   [xG NOT SEEN YET]"), flush=True)
        lost = ", ".join("%s %d" % (k.replace("_", " "), v)
                         for k, v in sorted(self.lost.items()) if v)
        if lost:
            print("   lost to data: %s   (evaluations the feed made impossible, "
                  "running total for the day)" % lost, flush=True)
        self.skipped = 0

    def _quota_guard(self):
        """Watch the day's remaining allowance and slow down before hitting it.

        Startup-only budgeting is not enough - the key is shared, and on
        2026-08-16 a morning coverage sweep drained it while the monitor was
        already running, which took the evening offline. Warn on Telegram while
        there is still time to intervene, then stretch the poll interval so
        whatever is left covers the rest of the night instead of being spent at
        full speed an hour early.
        """
        self.polls += 1
        if self.polls % config.QUOTA_CHECK_POLLS:
            return
        used, limit = apifootball.quota(self.api)
        if used is None:
            return
        left = max(limit - used, 0)
        was = self.quota_frac
        self.quota_frac = (float(used) / limit) if limit else 0.0
        print("   quota: %d of %d used, %d left" % (used, limit, left), flush=True)
        if config.SLOW_POLL and was < config.SLOW_POLL_FROM_QUOTA <= self.quota_frac:
            print("   quota at %.0f%% - adaptive polling ARMED (was off)"
                  % (100 * self.quota_frac), flush=True)
        elif config.SLOW_POLL and self.quota_frac < config.SLOW_POLL_FROM_QUOTA <= was:
            print("   quota back under %.0f%% - adaptive polling stood down"
                  % (100 * config.SLOW_POLL_FROM_QUOTA), flush=True)
        if left > config.QUOTA_WARN:
            return

        if left <= config.QUOTA_SLOW and self.poll_seconds < config.QUOTA_POLL_MAX:
            self.poll_seconds = min(self.poll_seconds * 2, config.QUOTA_POLL_MAX)
            print("   slowing to POLL=%ds to stretch the remaining quota"
                  % self.poll_seconds, flush=True)
        if self.quota_warned:
            return
        self.quota_warned = True
        self.tg.send("API quota running low: %d of %d left. Polling slowed to "
                     "%ds. If this keeps dropping the monitor will go blind - "
                     "quota resets 00:00 UTC."
                     % (left, limit, self.poll_seconds))

    @staticmethod
    def _win_mark(ev):
        """Momentum-window marker: '~' none (blocked), '*' shortened but real,
        ' ' the full window. review.py parses this single character, so the set
        stays one char wide."""
        if ev.approx:
            return "~"
        return " " if ev.win_min >= config.WINDOW else "*"

    def _feed_health(self):
        """Say out loud when the feed dies, and when it comes back.

        An entitlement failure (expired subscription, plan cap) arrives as a
        200 with an empty response list, so the monitor cheerfully reports
        "0 live, 0 watched" and keeps polling. Without this it is silent: on
        2026-08-16 the account started refusing every request at ~17:15 and the
        monitor showed nothing wrong for 85 minutes. A dead feed means no alert
        can ever fire, so it has to be louder than a quiet evening.
        """
        err = getattr(self.api, "last_error", None)
        if err:
            self.lost["feed_fail"] += 1
        if not err:
            if self.feed_bad >= config.FEED_BAD_POLLS:
                self.tg.send("Feed recovered - API-Football is answering again.")
            self.feed_bad = 0
            return

        self.feed_bad += 1
        if self.feed_bad < config.FEED_BAD_POLLS:
            return
        if self._now - self.feed_alerted < config.FEED_ALERT_COOLDOWN:
            return
        self.feed_alerted = self._now
        self.tg.send("MONITOR IS BLIND - API-Football is refusing requests "
                     "(%d polls).\n%s\nNo alerts can fire until this clears; "
                     "check the API-Football dashboard." % (self.feed_bad, err))

    def _poll_fixture(self, fx, prices):
        self._last_watched = False
        lg = fx.get("league") or {}
        if self.league_ids and lg.get("id") not in self.league_ids:
            return
        f = fx.get("fixture") or {}
        fid = str(f.get("id"))
        minute = (f.get("status") or {}).get("elapsed") or 0
        if minute < config.CHECKPOINTS[0] - config.WINDOW - config.RECORD_LEAD:
            return

        teams, goals = fx.get("teams") or {}, fx.get("goals") or {}
        home, away = teams.get("home") or {}, teams.get("away") or {}
        hs, as_ = int(goals.get("home") or 0), int(goals.get("away") or 0)

        fav = apifootball.prematch_favourite(self.api, fid, self.prematch)
        if not fav:
            return
        side, pm = fav
        if not (config.MIN_ODDS <= pm <= config.MAX_ODDS):
            return
        self._last_watched = True

        fav_id = (home if side == "home" else away).get("id")
        opp_id = (away if side == "home" else home).get("id")
        if not self._due_for_poll(fid, minute):
            self.skipped += 1
            return                           # still watched, just not re-measured
        rows = self.api.get("/fixtures/statistics", fixture=fid)
        fstat, seen_f = apifootball.parse_stats(rows, fav_id)
        ostat, seen_o = apifootball.parse_stats(rows, opp_id)
        self.xg_seen = self.xg_seen or seen_f or seen_o
        # reuse the last non-empty stats over a feed gap (before recording history
        # so momentum deltas are not corrupted by a spurious drop to zero)
        fstat, ostat, _carried = self._carry_stats(fid, fstat, ostat)
        # strip penalty attempts BEFORE history is recorded, or the momentum
        # window keeps differencing contaminated snapshots
        fstat, ostat = self._strip_penalties(fid, minute, fstat, ostat,
                                             fav_id, opp_id, label_hint=(
                                                 home.get("name"), away.get("name")))
        fav_goals, opp_goals = (hs, as_) if side == "home" else (as_, hs)

        h = self.history.setdefault(fid, [])
        if not h or h[-1].minute < minute:
            h.append(rules.Snapshot(minute, dict(fstat), dict(ostat), fav_goals))

        fav_name = (home if side == "home" else away).get("name")
        label = "%s %d-%d %s" % (home.get("name"), hs, as_, away.get("name"))
        done = self.done.setdefault(fid, set())
        cp = rules.due_checkpoint(done, minute)
        leading = fav_goals > opp_goals

        if leading:
            print("   %-38s %2d' fav=%-14s %s  cp=%s (leading)"
                  % (label, minute, fav_name,
                     self.brief(fstat, ostat,
                                rules.thresholds(minute, fav_goals=fav_goals,
                                                 opp_goals=opp_goals)[0]),
                     cp), flush=True)
            return

        ev = rules.evaluate(self.history, fid, minute, fstat, ostat,
                            fav_goals, opp_goals)
        self.last_conv[fid] = ev.conv
        if ev.approx:
            self.lost["no_window"] += 1          # judged blind: feed gap
        if ev.n_present == 0:
            self.lost["no_stats"] += 1           # the feed never described it
        # When the favourite is behind the tradeable market is the double chance
        # (win or draw), not an outright win from behind. When level it is the
        # win market as before.
        behind = fav_goals < opp_goals
        fx_prices = prices.get(fid)
        if not fx_prices:
            cached = self.price_cache.get(fid)
            if cached and (self._now - cached[0]) <= config.PRICE_CARRY_TTL:
                fx_prices = cached[1]      # carry the last live odds over the gap
        pinfo = apifootball.signal_price(fx_prices, side, behind)
        price = self._sane_price(fid, pinfo["price"], label, pm)
        if price is None:
            self.lost["no_price"] += 1
        if price is None:
            pinfo = dict(pinfo, price=None)
        nd = ev.n_present
        print("   %-38s %2d' fav=%-14s %s vol=%d/%d mom=%d/%d%s conv=%.0f "
              "pm=%.2f odds=%s cp=%s"
              % (label, minute, fav_name, self.brief(fstat, ostat, ev.vol_th),
                 ev.vol_met, nd, ev.mom_met, nd, self._win_mark(ev), ev.conv,
                 pm, ("%.2f" % price) if price else "n/a", cp), flush=True)

        if cp is None or minute > config.CHECKPOINTS[-1] + 5:
            return
        # Do NOT spend the checkpoint on the first poll that reaches it. Feeds
        # publish in batches, so the first poll after cp often carries stale
        # numbers: Toulouse 0-0 Lyon (2026-08-22) was judged at 45' on shots=4,
        # conviction 23, and seconds later showed shots=9, xg=1.57, conviction
        # 67 - a clean signal already thrown away. The checkpoint stays open,
        # re-judged each poll, until it fires or its grace window closes.
        # _fire_decision still blocks any repeat that fails to beat the
        # fixture's conviction high, so this cannot nag.
        expired = minute >= cp + config.CHECKPOINT_GRACE
        if expired:
            done.add(cp)

        in_band = price is None or (config.PRICE_FLOOR <= price <= config.PRICE_CEIL)
        # With PRICE_GATE off the quoted price no longer vetoes a signal - it is
        # a bookmaker number and the bet goes on an exchange at a better one.
        price_ok = in_band or not config.PRICE_GATE

        # MINIMUM PRICE FOR AN EDGE. Replaces the old time factor: instead of
        # suppressing the SCORE late in a match, demand a longer PRICE, because
        # fewer minutes left means a lower chance of the goal the bet needs.
        # Only bites when a price is actually quoted - with none there is
        # nothing to test, and the alert still goes out unsized (Alf confirmed
        # 2026-09-19 that firing blind is intended, not a defect to be fixed).
        # A quote within EDGE_TOLERANCE of the requirement now FIRES rather than
        # being refused; the alert reports the requirement so the shortfall is
        # explicit. See config.EDGE_TOLERANCE.
        state = "behind" if fav_goals < opp_goals else "level"
        # `pm` is the PRE-MATCH price and is worth more to the estimate than the
        # evidence is; see config.WINP_PM_POINTS. It is always available here -
        # the watchlist is selected on it - so the price-blind path is only ever
        # taken by callers outside the monitor.
        need = rules.min_price(state, minute, ev.conv, pm)
        edge_ok = True
        short_by = 0.0
        if config.MIN_ODDS_GATE and price is not None and ev.ok:
            edge_ok = price >= need - config.EDGE_TOLERANCE
            if edge_ok and price < need:
                short_by = need - price

        if fid in self.acked or fid in self.muted:
            print("       cp%d: signal suppressed - %s" %
                  (cp, "bet already logged" if fid in self.acked else "ignored by Alf"),
                  flush=True)
            return
        if not (ev.ok and price_ok and edge_ok):
            why = ["vol %d/%d mom %d/%d [%s]"
                   % (ev.vol_met, nd, ev.mom_met, nd, ev.basis)]
            if ev.approx:
                why.append("no momentum window >= %dmin" % config.MIN_WINDOW)
            elif ev.win_min < config.WINDOW:
                why.append("momentum window %dmin (feed late)" % ev.win_min)
            if not price_ok:
                why.append("price %.2f outside %.2f-%.2f"
                           % (price, config.PRICE_FLOOR, config.PRICE_CEIL))
            if not edge_ok:
                why.append("price %.2f below %.2f needed for an edge "
                           "(%s, %d', pm %.2f, P(win) %.0f%%)"
                           % (price, need, state, minute, pm,
                              100 * rules.win_probability(state, minute,
                                                          ev.conv, pm)))
            print("       cp%d %s: %s"
                  % (cp, "no signal" if expired else "not yet (window open)",
                     "; ".join(why)), flush=True)
            if ev.ok:
                # the evidence was there; something else refused it. Worth
                # recording - this is the population the gate is judged on.
                bad = "+".join([t for t, k in (("band", price_ok),
                                               ("price", edge_ok)) if not k])
                self._record_block(fid, cp, dict(
                    league=lg.get("name"), label=label, minute=minute,
                    state=state, side=side, market=pinfo["market"],
                    fav=fav_name, score="%d-%d" % (hs, as_), conv=ev.conv,
                    vol_met=ev.vol_met, mom_met=ev.mom_met, n_present=nd,
                    pm=pm, price=price, need=need,
                    winp=rules.win_probability(state, minute, ev.conv, pm)),
                    bad or "other")
            return

        # conviction gate: must clear the floor to fire at all, and only re-fire
        # when it beats the highest conviction already alerted for this fixture.
        fire, reason = self._fire_decision(fid, ev.conv)
        if not fire:
            print("       cp%d %s" % (cp, reason), flush=True)
            self._record_block(fid, cp, dict(
                league=lg.get("name"), label=label, minute=minute, state=state,
                side=side, market=pinfo["market"], fav=fav_name,
                score="%d-%d" % (hs, as_), conv=ev.conv, vol_met=ev.vol_met,
                mom_met=ev.mom_met, n_present=nd, pm=pm, price=price, need=need,
                winp=rules.win_probability(state, minute, ev.conv, pm)),
                "conviction")
            return

        # ONE ALERT PER CHECKPOINT. Checkpoints are 5 minutes apart, so this is
        # the repeat cadence: 45, 50, 55 ... not once per poll.
        #
        # Added 2026-09-12. The block below deliberately does NOT spend a
        # checkpoint on an unsizable (odds=n/a) alert, and its comment relied on
        # "_fire_decision's rising-only rule stops it nagging" -- which was
        # removed on 2026-09-07 when alerts were made to repeat. With both
        # changes in place an unpriced signal re-fired on EVERY poll: Le Havre
        # 0-0 Angers sent six identical conv=72 stake=0 alerts inside one
        # checkpoint window. Spending the checkpoint is still withheld (a price
        # arriving seconds later must have something to fire on); what is
        # tracked here is only whether Alf has ALREADY been told about this
        # checkpoint.
        cp_key = "%s:%d" % (fid, cp)
        if cp_key in self.alerted_cp:
            print("       cp%d: already alerted this checkpoint, not repeating"
                  % cp, flush=True)
            return
        self.alerted_cp.add(cp_key)
        # Spend the checkpoint - but NOT if the alert was unsizable. With no live
        # price the signal still fires (price_ok is True when price is None) and
        # reaches Telegram with stake 0, which is information but not a bet. If
        # that consumed the checkpoint, a price appearing seconds later would
        # have nothing left to fire on. Feyenoord 0-1 ADO Den Haag (2026-08-30)
        # fired at 45' on conv 85 / vol 4/4 / mom 4/4 with odds=n/a, and by 50'
        # was conv 90 with a price - but cp45 was already gone. The grace window
        # still closes it via `expired` above, so this cannot stay open forever,
        # and _fire_decision's rising-only rule stops it nagging.
        if price is not None:
            done.add(cp)

        # exclude this fixture's own reserved exposure: the alerts for one
        # fixture are ALTERNATIVES, not additive bets, so a repeat must not
        # be starved by its own earlier suggestion. Mirrors quote() above.
        open_total = sum(v for k, v in self.open_pos.items() if k != fid)
        # Never size off an out-of-band quote: base = TARGET_WIN/(price-1), so a
        # 1.20 would imply a 5000 base and suggest the per-bet cap on a price
        # nobody should take. Clamp into the band instead - the alert reports
        # both the quote and the price the stake was computed at.
        size_price, clamped = price, None
        if price is not None and not in_band and config.SIZE_PRICE_CLAMP:
            size_price = min(max(price, config.PRICE_FLOOR), config.PRICE_CEIL)
            clamped = size_price
        sz = (sizing.size(size_price, ev.conv, open_total) if size_price
              else dict(stake=0.0, base=0.0, mult=1.0, want=0.0, kelly=0.0,
                        bound="no price"))
        if clamped is not None:
            sz["bound"] = "%s, sized at %.2f (quote %.2f out of band)" % (
                sz["bound"], clamped, price)
        ctx = dict(label=label, league=lg.get("name"), minute=minute,
                   fav=fav_name, side=side, score="%d-%d" % (hs, as_),
                   conv=ev.conv, price=price, market=pinfo["market"],
                   kind=pinfo["kind"], derived=pinfo["derived"],
                   need=need, state=state, short_by=short_by,
                   winp=rules.win_probability(state, minute, ev.conv, pm),
                   pm=pm)
        self.last_alert[fid] = ctx
        self.best_conv[fid] = ev.conv
        mid = self.tg.send(self.alert_text(ctx, ev, sz, price, pm))
        if mid:
            self.msg2fid[str(mid)] = fid
        if sz["stake"] > 0:
            self.open_pos[fid] = sz["stake"]
        print("   >>> SIGNAL %s conv=%.0f stake=%.0f (%s)"
              % (label, ev.conv, sz["stake"], ev.basis), flush=True)
        # RECORD THE ACCEPTED POPULATION TOO, not only the refusals. Without it
        # the ledger can never answer whether the gate is too LENIENT: every row
        # is a refusal, so a price far above the requirement never appears -
        # those are accepted and become signals. Asked for 2026-09-21 when a
        # live price ceiling could not be calibrated for exactly that reason
        # (Benfica 21.00 against a 2.56 requirement, twelve such sightings in a
        # week, and no data anywhere to say where the line should sit).
        # Recorded with blocked_by="fired" so the two populations stay separable.
        self._record_block(fid, cp, dict(
            league=lg.get("name"), label=label, minute=minute, state=state,
            side=side, market=pinfo["market"], fav=fav_name,
            score="%d-%d" % (hs, as_), conv=ev.conv, vol_met=ev.vol_met,
            mom_met=ev.mom_met, n_present=nd, pm=pm, price=price, need=need,
            winp=rules.win_probability(state, minute, ev.conv, pm)), "fired")
        self.save()
