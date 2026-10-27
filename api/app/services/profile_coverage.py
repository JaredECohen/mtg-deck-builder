"""How much of the card table has a profile row.

A full Scryfall ingest is about 35,000 cards. Profiling only Modern-legal
cards leaves that near 65%, and the optimizer then has no profile for the
Commander and Legacy cards it is asked about. The CI fixture is a ~2,000 card
cut and is healthy at the old 60% bar; a 35,000 card database is not.
"""

from __future__ import annotations


# At or above this many cards we are looking at a real ingest, not the fixture.
FULL_INGEST_CARDS = 10_000
FULL_INGEST_TARGET = 0.90
FIXTURE_TARGET = 0.60


def coverage_report(cards: int, profiles: int) -> dict[str, int | float | str]:
    if cards <= 0:
        coverage = 0.0
        status = "ok"
        target = FIXTURE_TARGET
    else:
        coverage = profiles / cards
        target = FULL_INGEST_TARGET if cards >= FULL_INGEST_CARDS else FIXTURE_TARGET
        status = "ok" if coverage >= target else "stale"
    return {
        "status": status,
        "cards": int(cards),
        "profiles": int(profiles),
        "coverage": round(coverage, 4),
        "target": target,
    }
