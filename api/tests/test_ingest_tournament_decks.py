from pathlib import Path

from app.db import session_scope
from app.db_models import TournamentDeck
from app.scripts.ingest_deck_source import normalize_raw_deck, normalized_record_payload
from app.services.card_repository import CardRepository
from app.services.database_bootstrap import create_schema


def test_normalize_raw_deck_populates_extended_metadata() -> None:
    repository = CardRepository()
    raw_deck = {
        "id": "commander-demo-1",
        "source": "fixture",
        "source_url": "https://example.com/decks/1",
        "event_name": "Commander League Finals",
        "event_date": "2025-03-01",
        "format": "commander",
        "format_season": "spring-2025",
        "event_tier": "league",
        "event_size": 64,
        "finish_label": "Top 8",
        "confidence": 0.92,
        "player_name": "Pilot",
        "placement": 5,
        "wins": 4,
        "losses": 1,
        "draws": 0,
        "commander": "The First Sliver",
        "mainboard": [
            {"name": "Cultivate", "quantity": 1},
            {"name": "Cultivate", "quantity": 1},
            {"name": "Forest", "quantity": 3},
        ],
        "sideboard": [],
    }

    normalized = normalize_raw_deck(
        repository,
        raw_deck,
        source_name="fixture",
        ingested_from=Path("/tmp/fixture.json"),
    )

    assert normalized.source == "fixture"
    assert normalized.source_url == "https://example.com/decks/1"
    assert normalized.format_season == "spring-2025"
    assert normalized.event_tier == "league"
    assert normalized.event_size == 64
    assert normalized.finish_label == "Top 8"
    assert normalized.confidence == 0.92
    assert normalized.mainboard[0].name == "Cultivate"
    assert normalized.mainboard[0].quantity == 2
    assert normalized.metadata.ingested_from == "/tmp/fixture.json"


def test_normalized_record_payload_maps_metadata_to_db_columns() -> None:
    repository = CardRepository()
    raw_deck = {
        "id": "modern-demo-1",
        "event_name": "Modern Showcase",
        "format": "modern",
        "mainboard": [{"name": "Lightning Bolt", "quantity": 4}],
        "sideboard": [{"name": "Swords to Plowshares", "quantity": 2}],
    }

    normalized = normalize_raw_deck(
        repository,
        raw_deck,
        source_name="sample",
        ingested_from=Path("/tmp/sample.json"),
    )
    payload = normalized_record_payload(normalized)

    assert payload["source"] == "sample"
    assert payload["source_url"] is None
    assert payload["format_season"] is None
    assert payload["event_tier"] is None
    assert payload["event_size"] is None
    assert payload["finish_label"] is None
    assert payload["confidence"] is None
    assert payload["metadata_json"]["ingested_from"] == "/tmp/sample.json"
    assert payload["mainboard"] == [{"name": "Lightning Bolt", "quantity": 4}]


def test_normalized_payload_persists_extended_metadata_to_database() -> None:
    create_schema()
    repository = CardRepository()
    raw_deck = {
        "id": "db-persist-demo-1",
        "source": "fixture",
        "source_url": "https://example.com/decks/db-persist-demo-1",
        "event_name": "Legacy Championship",
        "event_date": "2025-04-05",
        "format": "legacy",
        "format_season": "2025-q2",
        "event_tier": "championship",
        "event_size": 128,
        "finish_label": "Runner-up",
        "confidence": 0.88,
        "player_name": "Tester",
        "placement": 2,
        "wins": 8,
        "losses": 1,
        "draws": 0,
        "mainboard": [{"name": "Lightning Bolt", "quantity": 4}],
        "sideboard": [{"name": "Swords to Plowshares", "quantity": 2}],
    }

    normalized = normalize_raw_deck(
        repository,
        raw_deck,
        source_name="fixture",
        ingested_from=Path("/tmp/db-fixture.json"),
    )
    payload = normalized_record_payload(normalized)

    with session_scope() as session:
        session.merge(TournamentDeck(**payload))

    with session_scope() as session:
        stored = session.get(TournamentDeck, "db-persist-demo-1")
        assert stored is not None
        assert stored.source_url == "https://example.com/decks/db-persist-demo-1"
        assert stored.format_season == "2025-q2"
        assert stored.event_tier == "championship"
        assert stored.event_size == 128
        assert stored.finish_label == "Runner-up"
        assert stored.confidence == 0.88
        assert stored.metadata_json["ingested_from"] == "/tmp/db-fixture.json"

        session.delete(stored)
