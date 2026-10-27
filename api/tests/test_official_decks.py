"""MTGJSON official-deck snapshot: what we keep, and that the file is real."""

import json

from app.config import DATA_DIR
from app.scripts.build_archetypes import evidence_for_source
from app.scripts.ingest_official_decks import (
    INCLUDED_TYPES,
    compact_deck,
    legal_fraction,
    select_summaries,
    to_raw_tournament,
)
from app.services.card_repository import CardRepository


def test_only_precons_and_pioneer_challenger_decks_are_kept() -> None:
    assert INCLUDED_TYPES == {"Commander Deck": "commander", "Pioneer Challenger Deck": "pioneer"}
    rows = [
        {"type": "Commander Deck", "fileName": "A", "name": "Real Precon"},
        {"type": "Commander Deck", "fileName": "B", "name": "Real Precon Collector's Edition"},
        {"type": "Theme Deck", "fileName": "C", "name": "Old Theme"},
        {"type": "Challenger Deck", "fileName": "D", "name": "Rotated Standard"},
        {"type": "Pioneer Challenger Deck", "fileName": "E", "name": "Izzet Phoenix"},
        {"type": "Pro Tour Deck", "fileName": "F", "name": "1996 Finalist"},
    ]
    selected = select_summaries({"data": rows})
    assert [row["fileName"] for row in selected] == ["A", "E"]


def test_compact_deck_keeps_names_quantities_and_commander() -> None:
    record = compact_deck(
        {"fileName": "GoblinRaid_XX", "name": "Goblin Raid", "type": "Commander Deck", "code": "XX"},
        {
            "name": "Goblin Raid",
            "type": "Commander Deck",
            "releaseDate": "2024-08-02",
            "code": "XX",
            "source": "https://magic.wizards.com/en/news/example",
            "commander": [{"name": "Krenko, Mob Boss", "count": 1, "colorIdentity": ["R"]}],
            "mainBoard": [
                {"name": "Mountain", "count": 38},
                {"name": "Sol Ring", "count": 1},
                {"name": "Krenko, Mob Boss", "count": 1},
            ],
            "sideBoard": [],
        },
    )
    assert record is not None
    assert record["id"] == "mtgjson-GoblinRaid_XX"
    assert record["format"] == "commander"
    assert record["commanders"] == ["Krenko, Mob Boss"]
    assert record["color_identity"] == ["R"]
    assert record["source_url"] == "https://magic.wizards.com/en/news/example"
    names = {card["name"]: card["quantity"] for card in record["mainboard"]}
    assert names["Mountain"] == 38
    assert "Krenko, Mob Boss" not in names
    raw = to_raw_tournament(record)
    assert raw["source"] == "mtgjson"
    assert raw["format"] == "commander"
    assert raw["commander"] == "Krenko, Mob Boss"
    assert raw["metadata"]["archetype_label"] == "Goblin Raid"


def test_doubled_double_faced_names_collapse() -> None:
    record = compact_deck(
        {"fileName": "Coin_XX", "name": "Coin Flip", "type": "Commander Deck"},
        {
            "name": "Coin Flip",
            "type": "Commander Deck",
            "commander": [{"name": "Zndrsplt, Eye of Wisdom // Zndrsplt, Eye of Wisdom", "colorIdentity": ["U", "R"]}],
            "mainBoard": [{"name": "Mountain // Mountain", "count": 2}, {"name": "Island", "count": 1}],
            "sideBoard": [],
        },
    )
    assert record is not None
    assert record["commanders"] == ["Zndrsplt, Eye of Wisdom"]
    assert record["mainboard"][0]["name"] == "Mountain"


def test_snapshot_is_a_real_official_catalog() -> None:
    document = json.loads((DATA_DIR / "official_decks.json").read_text(encoding="utf-8"))
    assert document["meta"]["license"] == "https://www.mtgjson.com/license/"
    decks = document["decks"]
    commanders = [deck for deck in decks if deck["format"] == "commander"]
    pioneer = [deck for deck in decks if deck["format"] == "pioneer"]
    assert len(commanders) >= 150
    assert len(pioneer) >= 4
    for deck in commanders:
        count = sum(card["quantity"] for card in deck["mainboard"])
        expected = 99 if len(deck["commanders"]) <= 1 else 98
        assert count == expected, deck["name"]
        assert deck["commanders"]
    for deck in pioneer:
        assert sum(card["quantity"] for card in deck["mainboard"]) == 60
        assert sum(card["quantity"] for card in deck["sideboard"]) == 15


def test_evidence_label_follows_the_representative_source() -> None:
    assert evidence_for_source("synthesized-from-builtin") == "template"
    assert evidence_for_source("sample") == "template"
    assert evidence_for_source("mtgjson") == "observed"


def test_legal_fraction_requires_enough_resolved_cards() -> None:
    repository = CardRepository()
    # Lightning Bolt is Modern-legal in the fixture; a handful of misses is not a shell.
    assert legal_fraction(repository, ["Lightning Bolt"], "modern") == 0.0
    names = ["Lightning Bolt"] * 8
    assert legal_fraction(repository, names, "modern") == 1.0
