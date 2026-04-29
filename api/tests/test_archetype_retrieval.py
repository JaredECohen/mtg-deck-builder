from app.db import session_scope
from app.db_models import Archetype, TournamentDeck
from app.scripts.build_archetypes import build_signature, deck_weight, main as build_archetypes_main
from app.scripts.ingest_tournament_decks import main as ingest_tournament_main
from app.services.card_repository import CardRepository


def test_deck_weight_uses_event_metadata() -> None:
    stronger = TournamentDeck(
        id="weight-1",
        source="curated_json",
        dedupe_key="weight-1",
        source_url=None,
        event_name="Showcase",
        event_date="2025-04-01",
        format="modern",
        format_season="2025-q2",
        event_tier="showcase",
        event_size=256,
        finish_label="Winner",
        confidence=0.9,
        player_name="A",
        placement=1,
        wins=7,
        losses=1,
        draws=0,
        colors=["U", "R"],
        tags=["spells"],
        commander=None,
        mainboard=[{"name": "Lightning Bolt", "quantity": 4}],
        sideboard=[],
        metadata_json={},
    )
    weaker = TournamentDeck(
        id="weight-2",
        source="sample",
        dedupe_key="weight-2",
        source_url=None,
        event_name="Local",
        event_date="2024-01-01",
        format="modern",
        format_season="2024-q1",
        event_tier="local",
        event_size=8,
        finish_label="Top 8",
        confidence=0.4,
        player_name="B",
        placement=8,
        wins=3,
        losses=2,
        draws=0,
        colors=["U", "R"],
        tags=["spells"],
        commander=None,
        mainboard=[{"name": "Lightning Bolt", "quantity": 4}],
        sideboard=[],
        metadata_json={},
    )
    assert deck_weight(stronger) > deck_weight(weaker)


def test_build_archetypes_enriches_metadata_and_commander_package() -> None:
    ingest_tournament_main([])
    build_archetypes_main()
    repository = CardRepository()

    modern = repository.top_archetypes(format_name="modern", colors=["U", "R"], theme_tags=["spells"], limit=1)[0]
    assert modern.metadata.land_packages
    assert modern.metadata.role_profile
    assert modern.metadata.mana_curve_profile
    assert modern.metadata.normalized_card_vector
    assert build_signature(repository, TournamentDeck(
        id="sig",
        source="sample",
        dedupe_key="sig",
        source_url=None,
        event_name="sig",
        event_date="2025-01-01",
        format="modern",
        format_season=None,
        event_tier=None,
        event_size=None,
        finish_label=None,
        confidence=None,
        player_name=None,
        placement=None,
        wins=None,
        losses=None,
        draws=None,
        colors=["U", "R"],
        tags=[],
        commander=None,
        mainboard=[{"name": "Lightning Bolt", "quantity": 4}],
        sideboard=[],
        metadata_json={},
    )).startswith("modern::")

    commander = repository.candidate_commander_packages(colors=["W", "U", "B", "R", "G"], theme_tags=["tribal"], limit=1)[0]
    assert commander.commander is not None
    assert commander.metadata.commander_package is not None
    assert commander.metadata.commander_package.ramp_package


def test_top_archetypes_strict_colors_excludes_superset_archetypes() -> None:
    """Regression: a 4-color shell should never outrank a 2-color match for a
    2-color request. `strict_colors=True` is the default and load-bearing —
    same class of bug we hit on the commander path."""
    ingest_tournament_main([])
    build_archetypes_main()
    repository = CardRepository()

    requested = {"U", "R"}
    strict = repository.top_archetypes(format_name="modern", colors=list(requested), limit=10, strict_colors=True)
    for archetype in strict:
        assert set(archetype.colors).issubset(requested), (
            f"strict_colors=True returned {archetype.name} with colors {archetype.colors} not in {requested}"
        )

    # Soft mode is permitted to return supersets — that's the explicit fallback.
    soft = repository.top_archetypes(format_name="modern", colors=list(requested), limit=10, strict_colors=False)
    assert len(soft) >= len(strict)


def test_repository_retrieval_methods_return_ranked_results() -> None:
    ingest_tournament_main([])
    build_archetypes_main()
    repository = CardRepository()

    archetypes = repository.top_archetypes(format_name="modern", colors=["U", "R"], theme_tags=["spells"], limit=3)
    assert archetypes
    assert archetypes[0].format == "modern"

    commanders = repository.candidate_commander_packages(colors=["W", "U", "B", "R", "G"], theme_tags=["tribal"], limit=3)
    assert commanders
    assert all(item.commander for item in commanders)

    packages = repository.card_packages_by_role_theme(format_name="commander", role="ramp", theme_tags=["tribal"], limit=5)
    assert packages
    assert "name" in packages[0]

    ranked = repository.rank_commanders(colors=["W", "U", "B", "R", "G"], theme_tags=["tribal"], limit=5)
    assert ranked
    assert ranked[0].colors

    profile = repository.get_commander_profile(ranked[0].name)
    assert profile is not None
    assert profile.strategy_summary

    planeswalker_profile = repository.get_commander_profile("Aminatou, the Fateshifter")
    assert planeswalker_profile is not None
    assert "Planeswalker" in planeswalker_profile.card.type_line

    colorless = repository.rank_commanders(colors=["C"], limit=10)
    assert colorless
    assert all(item.colors == [] for item in colorless)
