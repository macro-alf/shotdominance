"""Warm the cache for a set of seasons WITHOUT computing or printing anything.

    python -m backtest.prefetch --seasons 2014,2015,2016,2017,2018,2019

This exists to keep a holdout honest. Running the normal reporter over the
holdout to "just download it" would put its results on screen, and a holdout
you have already seen is not a holdout - you cannot un-see a number when
choosing which candidate to promote. So this fetches and caches only, printing
nothing but progress counts.
"""
import argparse

from . import sources


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--leagues", default=",".join(sources.LEAGUES))
    ap.add_argument("--seasons", required=True)
    a = ap.parse_args(argv)

    total = 0
    for season in [s.strip() for s in a.seasons.split(",") if s.strip()]:
        for lg in [x.strip() for x in a.leagues.split(",") if x.strip()]:
            matched, unmatched = sources.joined(lg, season)
            for i, fx in enumerate(matched, 1):
                try:
                    sources.match_shots(fx["match_id"])
                except Exception as e:
                    print("  ! %s %s %s: %s" % (lg, season, fx["match_id"], e),
                          flush=True)
                total += 1
                if i % 100 == 0:
                    print("  %s %s: %d/%d (%d cached overall)"
                          % (lg, season, i, len(matched), total), flush=True)
            print("%s %s cached: %d fixtures, %d unmatched on odds"
                  % (lg, season, len(matched), len(unmatched)), flush=True)
    print("done - %d fixtures cached" % total)


if __name__ == "__main__":
    main()
