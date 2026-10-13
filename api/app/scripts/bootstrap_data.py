"""Fill an empty database on first boot; refresh card data on demand.

The deployed API keeps its SQLite database on a persistent volume. On a fresh
volume there is nothing in it, so before the server starts this runs the data
pipeline in order (README "Postgres data pipeline"), skipping every step whose
output already exists, so ordinary restarts cost a few database counts:

1. ``ingest_scryfall``       - cards (only when the cards table is nearly empty,
                               or always with ``--refresh-cards``)
2. ``ingest_tournament_decks`` - the curated template corpus (when empty)
3. ``build_archetypes``      - archetypes (when empty, or after new decks)
4. ``build_card_profiles``   - after an ingest or when none exist (incremental)

Usage::

    python -m app.scripts.bootstrap_data                  # first boot / no-op
    python -m app.scripts.bootstrap_data --refresh-cards  # weekly card refresh

The running API caches cards in memory at startup, so restart it after a
refresh. In the deployed container the weekly GitHub Action drops a flag
file that `deploy/start.sh` acts on at boot, so the re-ingest never runs
alongside a live server (both together exceed the 1 GB machine).
"""

from __future__ import annotations

import argparse
import json
import time

from sqlalchemy import func, select

from app.db import session_scope
from app.db_models import Archetype, Card, CardProfile, TournamentDeck
from app.services.database_bootstrap import create_schema

# Fewer cards than this means the DB holds no real Scryfall ingest.
MIN_CARDS = 10_000


def _count(model) -> int:
    with session_scope() as session:
        return int(session.scalar(select(func.count()).select_from(model)) or 0)


def run(refresh_cards: bool = False) -> dict[str, object]:
    create_schema()
    steps: dict[str, object] = {}

    def step(name: str, fn) -> None:
        started = time.perf_counter()
        fn()
        steps[name] = round(time.perf_counter() - started, 1)

    ingested = False
    if refresh_cards or _count(Card) < MIN_CARDS:
        from app.scripts.ingest_scryfall import main as ingest_scryfall

        step("ingest_scryfall", ingest_scryfall)
        ingested = True

    new_decks = False
    if _count(TournamentDeck) == 0:
        from app.scripts.ingest_tournament_decks import main as ingest_tournament_decks

        step("ingest_tournament_decks", lambda: ingest_tournament_decks([]))
        new_decks = True

    if new_decks or _count(Archetype) == 0:
        from app.scripts.build_archetypes import main as build_archetypes

        step("build_archetypes", build_archetypes)

    if ingested or _count(CardProfile) == 0:
        from app.scripts.build_card_profiles import main as build_card_profiles

        step("build_card_profiles", lambda: build_card_profiles([]))
    steps["cards"] = _count(Card)
    return steps


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Bootstrap or refresh the card database.")
    parser.add_argument("--refresh-cards", action="store_true", help="Re-ingest Scryfall even if cards exist")
    args = parser.parse_args(argv)
    print(json.dumps({"bootstrap": run(refresh_cards=args.refresh_cards)}))


if __name__ == "__main__":
    main()
