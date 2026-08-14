#!/usr/bin/env python3
"""In-play shot-dominance monitor - entry point.

    python monitor.py --stats    dump every stat type the feed returns (xG check)
    python monitor.py --once     resolve leagues, one poll, exit
    python monitor.py            run forever

It never places bets. It alerts when a pre-match favourite is failing to win but
dominating the shot count, and records bets you tell it you placed by replying
"bet done" to the alert in Telegram.
"""
import sys
import time

from shotdominance import apifootball, config, engine, telegram


def main():
    if not config.API_KEY:
        sys.exit("APIFOOTBALL_KEY not set")
    arg = sys.argv[1] if len(sys.argv) > 1 else ""

    api = apifootball.ApiClient()
    if arg == "--stats":
        apifootball.show_stats(api)
        return

    tg = telegram.Telegram()
    print("Resolving competitions...", flush=True)
    ids = apifootball.resolve_leagues(api)
    mon = engine.Monitor(api, tg, ids)
    mon.load()

    print("gates: fav %.2f-%.2f | cp %s | window %d' | dominance opp<=%.0f%% | "
          "price %.2f-%.2f | target win %.0f"
          % (config.MIN_ODDS, config.MAX_ODDS, config.CHECKPOINTS, config.WINDOW,
             config.DOM_RATIO * 100, config.PRICE_FLOOR, config.PRICE_CEIL,
             config.TARGET_WIN), flush=True)
    tg.send("Monitor started. Watching %d competitions." % len(ids))

    if arg == "--once":
        mon.poll()
        return
    while True:
        try:
            mon.poll()
        except Exception as e:
            print("poll failed:", e, flush=True)
        time.sleep(config.POLL_SECONDS)


if __name__ == "__main__":
    main()
