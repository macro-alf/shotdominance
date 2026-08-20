"""API-client failures must be capturable by the caller.

daily.py's own requests used to print to stdout only, so a failed /fixtures
call left nothing in logs/daily-*.log and the 2026-08-19 early stop had to be
inferred from the monitor log rather than read.
"""
import pytest

from shotdominance import apifootball


@pytest.fixture(autouse=True)
def restore_logger():
    yield
    apifootball.set_logger(None)          # never leak a sink between tests


class BoomSession:
    headers = {}

    def get(self, *a, **k):
        raise RuntimeError("connection reset")

    def update(self, *a, **k):
        pass


def _client():
    api = apifootball.ApiClient(key="x")
    api.session = BoomSession()
    api.gap = 0.0
    return api


def test_request_failure_reaches_the_injected_sink():
    seen = []
    apifootball.set_logger(seen.append)
    assert _client().get("/fixtures", date="2026-08-19") == []
    assert len(seen) == 1 and "/fixtures failed" in seen[0]
    assert "connection reset" in seen[0]


def test_default_sink_still_prints(capsys):
    assert _client().get("/fixtures") == []
    assert "/fixtures failed" in capsys.readouterr().out


def test_set_logger_none_restores_the_default(capsys):
    apifootball.set_logger(lambda m: None)
    apifootball.set_logger(None)
    _client().get("/fixtures")
    assert "/fixtures failed" in capsys.readouterr().out
