import json
from pathlib import Path

from app.db import session_scope
from app.db_models import TournamentDeck
from app.scripts.ingest_tournament_decks import ingest_sources, load_source
from app.services.database_bootstrap import create_schema


FIXTURES = Path(__file__).parent / "fixtures"


def cleanup_decks(*deck_ids: str) -> None:
    with session_scope() as session:
        for deck_id in deck_ids:
            stored = session.get(TournamentDeck, deck_id)
            if stored is not None:
                session.delete(stored)


def test_json_source_adapter_loads_decks() -> None:
    decks = load_source(FIXTURES / "decks_curated.json", "json")
    assert len(decks) == 1
    assert decks[0]["id"] == "json-modern-1"
    assert decks[0]["event_tier"] == "rcq"


def test_csv_source_adapter_loads_commander_decks() -> None:
    decks = load_source(FIXTURES / "decks_commander.csv", "csv")
    assert len(decks) == 1
    assert decks[0]["commander"] == "The First Sliver"
    assert decks[0]["mainboard"][0] == {"name": "Cultivate", "quantity": 1}


def test_ingest_sources_persists_commander_csv_metadata() -> None:
    create_schema()
    cleanup_decks("commander-csv-1")
    result = ingest_sources([(FIXTURES / "decks_commander.csv", "csv", "commander_csv")])

    assert result["inserted"] >= 1

    with session_scope() as session:
        stored = session.get(TournamentDeck, "commander-csv-1")
        assert stored is not None
        assert stored.commander == "The First Sliver"
        assert stored.source == "commander_csv"
        assert stored.event_tier == "league"
        assert stored.event_size == 32
        assert stored.confidence == 0.93
        assert stored.metadata_json["ingested_from"].endswith("decks_commander.csv")

        session.delete(stored)


def test_ingest_sources_dedupes_and_prefers_higher_priority_source() -> None:
    create_schema()
    duplicate_path = FIXTURES / "decks_duplicate_sample.json"
    preferred_path = FIXTURES / "decks_duplicate_curated.json"
    duplicate_path.write_text(
        json.dumps(
            [
                {
                    "id": "duplicate-sample-1",
                    "source": "sample",
                    "source_url": "https://example.com/shared-dup",
                    "event_name": "Shared Event",
                    "format": "modern",
                    "event_tier": "local",
                    "confidence": 0.4,
                    "mainboard": [{"name": "Lightning Bolt", "quantity": 4}],
                    "sideboard": [],
                }
            ]
        )
    )
    preferred_path.write_text(
        json.dumps(
            {
                "decks": [
                    {
                        "id": "duplicate-curated-1",
                        "source": "curated_json",
                        "source_url": "https://example.com/shared-dup",
                        "event_name": "Shared Event",
                        "event_date": "2025-05-01",
                        "format": "modern",
                        "event_tier": "rcq",
                        "confidence": 0.81,
                        "mainboard": [{"name": "Lightning Bolt", "quantity": 4}],
                        "sideboard": [],
                    }
                ]
            }
        )
    )
    try:
        cleanup_decks("duplicate-sample-1", "duplicate-curated-1")
        first = ingest_sources([(duplicate_path, "json", "sample")])
        second = ingest_sources([(preferred_path, "json", "curated_json")])

        assert first["inserted"] == 1
        assert second["replaced"] >= 1

        with session_scope() as session:
            stored = session.get(TournamentDeck, "duplicate-sample-1")
            assert stored is not None
            assert stored.source == "curated_json"
            assert stored.event_tier == "rcq"
            assert stored.confidence == 0.81
            session.delete(stored)
    finally:
        duplicate_path.unlink(missing_ok=True)
        preferred_path.unlink(missing_ok=True)
