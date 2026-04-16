from __future__ import annotations

import json
from collections import Counter

from sqlalchemy.dialects.postgresql import insert

from app.config import TOURNAMENT_DECK_PATH
from app.db import session_scope
from app.db_models import IngestionRun, TournamentDeck
from app.services.card_repository import CardRepository
from app.services.database_bootstrap import create_schema


def merge_refs(refs: list[dict[str, object]]) -> list[dict[str, object]]:
    counts = Counter[str]()
    for ref in refs:
        counts[str(ref["name"])] += int(ref["quantity"])
    return [{"name": name, "quantity": quantity} for name, quantity in counts.items()]


def infer_colors_and_tags(repository: CardRepository, refs: list[dict[str, object]], commander: str | None) -> tuple[list[str], list[str]]:
    colors: set[str] = set()
    tags: Counter[str] = Counter()
    names = [str(ref["name"]) for ref in refs]
    if commander:
        names.append(commander)
    for card in repository.get_cards(names):
        colors.update(card.color_identity or card.colors)
        for tag in card.tags:
            if tag != "land":
                tags[tag] += 1
    top_tags = [tag for tag, _ in tags.most_common(6)]
    return sorted(colors), top_tags


def normalize_deck(repository: CardRepository, raw_deck: dict[str, object]) -> dict[str, object]:
    mainboard = merge_refs(list(raw_deck.get("mainboard", [])))
    sideboard = merge_refs(list(raw_deck.get("sideboard", [])))
    commander = raw_deck.get("commander")
    colors, tags = infer_colors_and_tags(repository, mainboard, commander if isinstance(commander, str) else None)

    return {
        "id": raw_deck["id"],
        "source": raw_deck.get("source", "unknown"),
        "event_name": raw_deck["event_name"],
        "event_date": raw_deck.get("event_date"),
        "format": raw_deck["format"],
        "player_name": raw_deck.get("player_name"),
        "placement": raw_deck.get("placement"),
        "wins": raw_deck.get("wins"),
        "losses": raw_deck.get("losses"),
        "draws": raw_deck.get("draws"),
        "colors": colors,
        "tags": tags,
        "commander": commander if isinstance(commander, str) else None,
        "mainboard": mainboard,
        "sideboard": sideboard,
        "metadata": {
            "raw_source": raw_deck.get("source", "unknown"),
            "ingested_from": str(TOURNAMENT_DECK_PATH),
        },
    }


def main() -> None:
    create_schema()
    repository = CardRepository()
    with TOURNAMENT_DECK_PATH.open() as handle:
        raw_decks = json.load(handle)

    processed = 0
    with session_scope() as session:
        run = IngestionRun(source="tournament_decks", status="running", records_processed=0)
        session.add(run)
        session.flush()

        for raw_deck in raw_decks:
            normalized = normalize_deck(repository, raw_deck)
            stmt = insert(TournamentDeck).values(**normalized)
            stmt = stmt.on_conflict_do_update(
                index_elements=[TournamentDeck.id],
                set_={
                    "source": stmt.excluded.source,
                    "event_name": stmt.excluded.event_name,
                    "event_date": stmt.excluded.event_date,
                    "format": stmt.excluded.format,
                    "player_name": stmt.excluded.player_name,
                    "placement": stmt.excluded.placement,
                    "wins": stmt.excluded.wins,
                    "losses": stmt.excluded.losses,
                    "draws": stmt.excluded.draws,
                    "colors": stmt.excluded.colors,
                    "tags": stmt.excluded.tags,
                    "commander": stmt.excluded.commander,
                    "mainboard": stmt.excluded.mainboard,
                    "sideboard": stmt.excluded.sideboard,
                    "metadata_json": stmt.excluded.metadata_json,
                },
            )
            session.execute(stmt)
            processed += 1

        run.status = "completed"
        run.records_processed = processed

    print(json.dumps({"status": "ok", "records_processed": processed}))


if __name__ == "__main__":
    main()
