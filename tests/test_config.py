"""Guards on the competition watchlist (Tier 1 + Tier 2, data-completeness
vetted 2026-08-16)."""
from shotdominance import config


def test_watchlist_size_and_uniqueness():
    assert len(config.LEAGUES) == 24
    assert len(set(config.LEAGUES)) == 24            # no duplicates


def test_every_league_is_pinned():
    # resolution must be bulletproof: every watched competition has a feed id
    for entry in config.LEAGUES:
        assert entry in config.PINNED_IDS, "unpinned: %r" % (entry,)
        assert isinstance(config.PINNED_IDS[entry], int)


def test_no_xgless_leagues_present():
    # Ligue 2 and Spain Segunda were dropped for having no xG at all
    assert ("France", "Ligue 2") not in config.LEAGUES
    assert ("Spain", "Segunda División") not in config.LEAGUES


def test_expected_additions_present():
    assert ("Ireland", "Premier Division") in config.LEAGUES
    assert ("Sweden", "Allsvenskan") in config.LEAGUES
    for uefa in ("UEFA Champions League", "UEFA Europa League",
                 "UEFA Europa Conference League"):
        assert ("World", uefa) in config.LEAGUES


# --- quota awareness --------------------------------------------------------
class StatusApi:
    def __init__(self, body):
        self.body = body

    def get(self, path, **p):
        return self.body


def test_quota_reads_status():
    from shotdominance import apifootball
    api = StatusApi({"requests": {"current": 5200, "limit_day": 7500}})
    assert apifootball.quota(api) == (5200, 7500)


def test_quota_is_unreadable_when_the_api_errors():
    """An exhausted account returns an empty LIST, not the status object. The
    supervisor must fall back rather than treat that as 'zero used'."""
    from shotdominance import apifootball
    assert apifootball.quota(StatusApi([])) == (None, None)
    assert apifootball.quota(StatusApi({})) == (None, None)
    assert apifootball.quota(StatusApi({"requests": {}})) == (None, None)
