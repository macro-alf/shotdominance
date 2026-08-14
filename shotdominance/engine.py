"""The monitor engine. One Monitor object owns all cross-poll state (history,
judged checkpoints, open exposure, acknowledgements, bets, telegram offset) -
replacing the module-level globals and monkeypatched functions of the old
seven-file chain.

The console output format is deliberately identical to the old build so that
review.py keeps parsing it, with one addition: the pre-match price is now
printed (pm=...) so the effect of the 1.30-2.25 gate is measurable.
"""
import time

from . import apifootball, blotter, config, rules, sizing, state


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

        # cross-poll / telegram state (persisted)
        self.acked = set()       # fids with a logged bet -> suppress alerts
        self.msg2fid = {}        # telegram message_id -> fid
        self.awaiting = {}       # chat_id -> fid (waiting for stake & price)
        self.bets = []           # blotter rows
        self.last_alert = {}     # fid -> context dict for record_bet
        self.offset = 0          # telegram getUpdates cursor
        self.xg_seen = False

    # --- persistence --------------------------------------------------------
    def save(self):
        state.save(config.STATE_PATH, {
            "acked": sorted(self.acked), "msg2fid": self.msg2fid,
            "await": self.awaiting, "bets": self.bets, "offset": self.offset})

    def load(self):
        d = state.load(config.STATE_PATH)
        if not d:
            return
        self.acked.update(d.get("acked", []))
        self.msg2fid.update({str(k): v for k, v in (d.get("msg2fid") or {}).items()})
        self.awaiting.update(d.get("await") or {})
        self.bets.extend(d.get("bets") or [])
        self.offset = d.get("offset", 0)
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

            # stage 2 - we asked for stake and price
            if chat in self.awaiting:
                nums = re.findall(r"\d+(?:[.,]\d+)?", text.replace(",", "."))
                if len(nums) >= 2:
                    fid = self.awaiting.pop(chat)
                    self.record_bet(fid, float(nums[0]), float(nums[1]))
                else:
                    self.tg.send("Need two numbers: stake then price, e.g. `650 2.60`")
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

    # --- blotter ------------------------------------------------------------
    def record_bet(self, fid, stake, price):
        ctx = self.last_alert.get(fid) or {}
        bet = blotter.new_bet(fid, ctx, stake, price)
        self.bets.append(bet)
        blotter.write(config.BLOTTER_PATH, self.bets)
        self.save()
        self.tg.send("Logged: %s, back %s, stake %.0f at %.2f. Settles at full "
                     "time." % (bet["match"] or fid, bet["back"], stake, price))
        print("   >>> BET LOGGED %s stake %.0f @ %.2f"
              % (bet["match"], stake, price), flush=True)

    def settle(self, live_ids):
        """Close out bets whose fixture has left the live board and finished."""
        changed = False
        for b in self.bets:
            if b["status"] != "open" or str(b["fixture_id"]) in live_ids:
                continue
            rows = self.api.get("/fixtures", id=b["fixture_id"])
            if not rows:
                continue
            fx = rows[0]
            st = ((fx.get("fixture") or {}).get("status") or {}).get("short")
            if st not in ("FT", "AET", "PEN"):
                continue
            g, t = fx.get("goals") or {}, fx.get("teams") or {}
            hs, as_ = int(g.get("home") or 0), int(g.get("away") or 0)
            home = (t.get("home") or {}).get("name")
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
        if price is None:
            lines += ["Price: NOT AVAILABLE - check manually", "",
                      "Stake: cannot size without a price"]
        else:
            lines += ["Price: %.2f  (%s; pre-match fav %.2f)"
                      % (price, price_tag, pm), "",
                      "Stake: %.0f EUR   [x%.2f on conviction, bound by %s]"
                      % (sz["stake"], sz["mult"], sz["bound"]),
                      "  target-win base %.0f, half-Kelly cap %.0f"
                      % (sz["base"], sz["kelly"])]
        lines += ["", "Basis: %s" % ev.basis,
                  "Scores: volume %.0f | momentum %.0f | dominance %.0f"
                  % (ev.s_vol, ev.s_mom, ev.s_dom),
                  "", "Cumulative (value/bar, opp as % of ours)",
                  "  " + "\n  ".join(ev.vol_det),
                  "", "Last %d min" % config.WINDOW,
                  "  " + "\n  ".join(ev.mom_det)]
        for x in ev.extra:
            lines += ["", x]
        lines += ["", "Reply 'bet done' TO THIS MESSAGE to stop repeats and log it.",
                  "Edge is a model assumption, not a measured quantity."]
        return "\n".join(lines)

    # --- one poll -----------------------------------------------------------
    def poll(self):
        self.receive()
        prices = apifootball.live_prices(self.api)
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
        for d in (self.history, self.done, self.open_pos):
            for k in [k for k in d if k not in live]:
                del d[k]

        print("   pacing: %d calls in %.0fs, %.0fs waiting, %d retries"
              % (self.api.calls - calls_before, time.time() - t0,
                 self.api.throttled, self.api.retries), flush=True)
        print("poll: %d live, %d watched, %d requests total%s"
              % (len(fixtures), watched, self.api.reqs,
                 "" if self.xg_seen else "   [xG NOT SEEN YET]"), flush=True)

    def _poll_fixture(self, fx, prices):
        self._last_watched = False
        lg = fx.get("league") or {}
        if self.league_ids and lg.get("id") not in self.league_ids:
            return
        f = fx.get("fixture") or {}
        fid = str(f.get("id"))
        minute = (f.get("status") or {}).get("elapsed") or 0
        if minute < config.CHECKPOINTS[0] - config.WINDOW:
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
        rows = self.api.get("/fixtures/statistics", fixture=fid)
        fstat, seen_f = apifootball.parse_stats(rows, fav_id)
        ostat, seen_o = apifootball.parse_stats(rows, opp_id)
        self.xg_seen = self.xg_seen or seen_f or seen_o
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
                                {k: config.BASE45[k] * minute / 45.0
                                 for k in config.KEYS}), cp), flush=True)
            return

        ev = rules.evaluate(self.history, fid, minute, fstat, ostat, fav_goals)
        # When the favourite is behind the tradeable market is the double chance
        # (win or draw), not an outright win from behind. When level it is the
        # win market as before.
        behind = fav_goals < opp_goals
        pinfo = apifootball.signal_price(prices.get(fid), side, behind)
        price = pinfo["price"]
        print("   %-38s %2d' fav=%-14s %s vol=%d/4 mom=%d/4%s conv=%.0f "
              "pm=%.2f odds=%s cp=%s"
              % (label, minute, fav_name, self.brief(fstat, ostat, ev.vol_th),
                 ev.vol_met, ev.mom_met, "~" if ev.approx else " ", ev.conv,
                 pm, ("%.2f" % price) if price else "n/a", cp), flush=True)

        if cp is None or minute > config.CHECKPOINTS[-1] + 5:
            return
        done.add(cp)

        price_ok = price is None or (config.PRICE_FLOOR <= price <= config.PRICE_CEIL)
        if fid in self.acked:
            print("       cp%d: signal suppressed - bet already logged" % cp,
                  flush=True)
            return
        if not (ev.ok and price_ok):
            why = ["vol %d/4 mom %d/4 [%s]" % (ev.vol_met, ev.mom_met, ev.basis)]
            if ev.approx:
                why.append("window incomplete")
            if not price_ok:
                why.append("price %.2f outside %.2f-%.2f"
                           % (price, config.PRICE_FLOOR, config.PRICE_CEIL))
            print("       cp%d no signal: %s" % (cp, "; ".join(why)), flush=True)
            return

        open_total = sum(self.open_pos.values())
        sz = (sizing.size(price, ev.conv, open_total) if price
              else dict(stake=0.0, base=0.0, mult=1.0, want=0.0, kelly=0.0,
                        bound="no price"))
        ctx = dict(label=label, league=lg.get("name"), minute=minute,
                   fav=fav_name, score="%d-%d" % (hs, as_), conv=ev.conv,
                   price=price, market=pinfo["market"], kind=pinfo["kind"],
                   derived=pinfo["derived"])
        self.last_alert[fid] = ctx
        mid = self.tg.send(self.alert_text(ctx, ev, sz, price, pm))
        if mid:
            self.msg2fid[str(mid)] = fid
        if sz["stake"] > 0:
            self.open_pos[fid] = sz["stake"]
        print("   >>> SIGNAL %s conv=%.0f stake=%.0f (%s)"
              % (label, ev.conv, sz["stake"], ev.basis), flush=True)
        self.save()
