"""Keep the test suite off the live files.

`engine.Monitor` saves cross-poll state (acked bets, the message->fixture map,
pending stake prompts, the Telegram offset) to `config.STATE_PATH` on every
poll, and the tests drive real `Monitor.poll()` calls. Without this fixture a
`pytest` run in the repo root rewrites the live `state3.json` the running
monitor depends on - a restart afterwards would come up with acknowledgements
and the Telegram offset wiped, re-processing old replies. The blotter is
redirected on the same principle: it is the only record of real bets.

Both are read as attributes at call time, so monkeypatching the module works.
"""
import pytest

from shotdominance import config


@pytest.fixture(autouse=True)
def isolate_live_files(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "STATE_PATH", str(tmp_path / "state3.json"))
    monkeypatch.setattr(config, "BLOTTER_PATH", str(tmp_path / "blotter.csv"))
