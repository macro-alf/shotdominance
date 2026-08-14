"""shotdominance - in-play shot-dominance football monitor.

A clean, single-package rebuild of the original seven-deep monkeypatch chain
(monitor2 -> run4 -> run5 -> run6 -> run7/monitor3). The rule set is the one
documented in HANDOVER.md; the API-adapter details (endpoints, field names,
market filtering, statistics parsing) are carried over verbatim from the live
copies because they were established empirically against the API-Football feed.

It never places bets. It alerts, and records bets you tell it you placed.
"""

__version__ = "3.0.0"
