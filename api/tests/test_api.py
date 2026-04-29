from fastapi.testclient import TestClient

from app.main import app
from app.scripts.build_archetypes import main as build_archetypes_main
from app.scripts.ingest_tournament_decks import main as ingest_tournament_main


client = TestClient(app)


def setup_module() -> None:
    ingest_tournament_main([])
    build_archetypes_main()


def test_health() -> None:
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["card_source"] in {"database", "sample"}


def test_generate_modern_deck() -> None:
    response = client.post(
        "/v1/decks/generate",
        json={
            "format": "modern",
            "colors": ["U", "R"],
            "playstyle_tags": ["aggro", "spells"],
            "theme_tags": ["prowess"],
            "mode": "constraint-aware",
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["format"] == "modern"
    assert len(payload["mainboard"]) > 0
    assert payload["score"]["legality"] == 100
    assert payload["is_legal"] is True
    assert payload["validation_errors"] == []
    assert "estimated_price_usd" in payload
    assert "sections" in payload
    assert "mechanics" in payload
    assert "role_summary" in payload
    assert "mana_curve" in payload


def test_validate_bad_deck() -> None:
    response = client.post(
        "/v1/decks/validate",
        json={
            "format": "modern",
            "mainboard": [{"name": "Lightning Bolt", "quantity": 8}],
            "sideboard": [],
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["is_legal"] is False
    assert payload["errors"]


def test_export_csv_format() -> None:
    generate_response = client.post(
        "/v1/decks/generate",
        json={
            "format": "modern",
            "colors": ["U", "R"],
            "playstyle_tags": ["aggro", "spells"],
            "theme_tags": ["prowess"],
        },
    )
    assert generate_response.status_code == 200
    deck = generate_response.json()

    export_response = client.post(
        "/v1/decks/export",
        json={
            "deck": deck,
            "target": "csv",
        },
    )
    assert export_response.status_code == 200
    payload = export_response.json()
    assert payload["target"] == "csv"
    assert payload["content"].startswith("section,quantity,name")


def test_refine_budget_prompt_changes_deck_and_reduces_price() -> None:
    generate_response = client.post(
        "/v1/decks/generate",
        json={
            "format": "modern",
            "colors": ["U", "R"],
            "playstyle_tags": ["aggro", "spells"],
            "theme_tags": ["prowess"],
        },
    )
    assert generate_response.status_code == 200
    deck = generate_response.json()

    refine_response = client.post(
        "/v1/decks/refine",
        json={
            "deck": deck,
            "refinement_prompt": "Make it cheaper while keeping the deck aggressive.",
        },
    )
    assert refine_response.status_code == 200
    refined = refine_response.json()
    assert refined["title"].endswith("Refined")
    assert refined["mainboard"] != deck["mainboard"]
    assert refined["estimated_price_usd"] < deck["estimated_price_usd"]
    assert refined["is_legal"] is True


def test_generate_deck_returns_full_sideboard_without_sideboard_land_penalty() -> None:
    response = client.post(
        "/v1/decks/generate",
        json={
            "format": "modern",
            "colors": ["U", "R"],
            "playstyle_tags": ["aggro", "spells"],
            "theme_tags": ["prowess"],
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["score"]["legality"] == 100
    assert sum(card["quantity"] for card in payload["sideboard"]) == 15
    assert not any("15-card sideboard" in warning for warning in payload["warnings"])


def test_generate_modern_lifegain_keeps_legal_legendary_playsets() -> None:
    response = client.post(
        "/v1/decks/generate",
        json={
            "format": "modern",
            "colors": ["W"],
            "playstyle_tags": ["lifegain"],
            "theme_tags": ["lifegain"],
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["is_legal"] is True
    assert payload["score"]["legality"] == 100
    heliod = next(card for card in payload["mainboard"] if card["name"] == "Heliod, Sun-Crowned")
    assert heliod["quantity"] == 4


def test_generate_standard_deck_filters_out_illegal_cards() -> None:
    response = client.post(
        "/v1/decks/generate",
        json={
            "format": "standard",
            "colors": ["R", "W"],
            "playstyle_tags": ["aggro"],
            "theme_tags": [],
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["is_legal"] is True
    assert payload["validation_errors"] == []
    assert payload["score"]["legality"] == 100


def test_card_detail_exposes_purchase_links() -> None:
    response = client.get("/v1/cards/Lightning Bolt")
    assert response.status_code == 200
    payload = response.json()["card"]
    assert "purchase_links" in payload
    assert "amazon_search" in payload["purchase_links"]


def test_data_status_endpoint() -> None:
    response = client.get("/api/data-status")
    assert response.status_code == 200
    payload = response.json()
    assert payload["card_count"] > 0
    assert payload["archetype_count"] > 0


def test_commander_generation_exposes_selection_reason_and_package_structure() -> None:
    response = client.post(
        "/v1/decks/generate",
        json={
            "format": "commander",
            "colors": ["W", "U", "B", "R", "G"],
            "playstyle_tags": ["tribal"],
            "theme_tags": ["slivers"],
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["commander"]
    assert payload["selected_archetype"]["metadata"]["commander_package"] is not None
    assert any("Selected" in item for item in payload["explanation"])
    assert sum(card["quantity"] for card in payload["mainboard"]) == 99


def test_commander_generation_reserves_reasonable_land_base() -> None:
    response = client.post(
        "/v1/decks/generate",
        json={
            "format": "commander",
            "colors": ["G", "U"],
            "playstyle_tags": ["ramp"],
            "theme_tags": [],
        },
    )
    assert response.status_code == 200
    payload = response.json()
    land_like = [
        card for card in payload["mainboard"]
        if card["name"] in {"Forest", "Island", "Plains", "Swamp", "Mountain"}
    ]
    assert sum(card["quantity"] for card in land_like) >= 30


def test_commander_search_and_detail_endpoints() -> None:
    search_response = client.get("/v1/commanders", params={"colors": "W,U,B,R,G", "theme_tags": "tribal", "limit": 5})
    assert search_response.status_code == 200
    search_payload = search_response.json()
    assert search_payload["commanders"]

    commander_name = search_payload["commanders"][0]["name"]
    detail_response = client.get(f"/v1/commanders/{commander_name}")
    assert detail_response.status_code == 200
    detail_payload = detail_response.json()["commander"]
    assert detail_payload["card"]["name"] == commander_name
    assert "strategy_summary" in detail_payload


def test_explicit_commander_selection_builds_around_requested_commander() -> None:
    response = client.post(
        "/v1/decks/generate",
        json={
            "format": "commander",
            "commander_name": "The First Sliver",
            "playstyle_tags": ["tribal"],
            "theme_tags": ["slivers"],
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["commander"] == "The First Sliver"
    assert any("explicitly chose" in item for item in payload["explanation"])
    assert set(payload["colors"]) == {"W", "U", "B", "R", "G"}


def test_invalid_explicit_commander_returns_400() -> None:
    response = client.post(
        "/v1/decks/generate",
        json={
            "format": "commander",
            "commander_name": "Lightning Bolt",
            "playstyle_tags": ["spells"],
        },
    )
    assert response.status_code == 400


def test_planeswalker_commander_is_searchable_and_buildable() -> None:
    search_response = client.get("/v1/commanders", params={"search": "Aminatou", "limit": 5})
    assert search_response.status_code == 200
    names = [item["name"] for item in search_response.json()["commanders"]]
    assert "Aminatou, the Fateshifter" in names

    generate_response = client.post(
        "/v1/decks/generate",
        json={
            "format": "commander",
            "commander_name": "Aminatou, the Fateshifter",
            "playstyle_tags": ["control"],
            "theme_tags": [],
        },
    )
    assert generate_response.status_code == 200
    payload = generate_response.json()
    assert payload["commander"] == "Aminatou, the Fateshifter"
    assert sum(card["quantity"] for card in payload["mainboard"]) == 99


def test_colorless_commander_search_returns_only_colorless_options() -> None:
    search_response = client.get("/v1/commanders", params={"colors": "C", "limit": 10})
    assert search_response.status_code == 200
    commanders = search_response.json()["commanders"]
    assert commanders
    assert all(item["colors"] == [] for item in commanders)


def test_card_search_endpoint_returns_matches() -> None:
    response = client.get("/v1/cards", params={"query": "Lightning", "format": "modern"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["cards"]
    assert any(card["name"] == "Lightning Bolt" for card in payload["cards"])


def test_parse_decklist_endpoint_supports_plain_text_sections() -> None:
    response = client.post(
        "/v1/decks/parse",
        json={
            "format": "modern",
            "deck_text": "Mainboard\n4 Lightning Bolt\n4 Monastery Swiftspear\n20 Mountain\n\nSideboard\n2 Spell Pierce",
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert any(card["name"] == "Lightning Bolt" and card["quantity"] == 4 for card in payload["mainboard"])
    assert any(card["name"] == "Spell Pierce" and card["quantity"] == 2 for card in payload["sideboard"])


def test_manual_deck_analysis_returns_structured_feedback() -> None:
    response = client.post(
        "/v1/decks/analyze",
        json={
            "format": "modern",
            "mainboard": [
                {"name": "Monastery Swiftspear", "quantity": 4},
                {"name": "Lightning Bolt", "quantity": 4},
                {"name": "Lava Dart", "quantity": 4},
                {"name": "Manamorphose", "quantity": 4},
                {"name": "Soul-Scar Mage", "quantity": 4},
                {"name": "Mountain", "quantity": 20},
                {"name": "Island", "quantity": 4},
                {"name": "Expressive Iteration", "quantity": 4},
                {"name": "Consider", "quantity": 4},
                {"name": "Dragon's Rage Channeler", "quantity": 4},
                {"name": "Mishra's Bauble", "quantity": 4},
            ],
            "sideboard": [{"name": "Spell Pierce", "quantity": 2}],
            "notes": "Tell me what shell this resembles and how to improve it.",
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["inferred_style"]
    assert payload["deck_health"]
    assert payload["game_plan_summary"]
    assert payload["play_pattern_summary"]
    assert payload["strengths"]
    assert payload["advice"]["possible_upgrades"]
    assert payload["nearest_shell_comparison"] is not None
    assert payload["swap_recommendations"]
    assert payload["swap_recommendations"][0]["cut_card"]
    assert payload["swap_recommendations"][0]["add_card"]


def test_commander_manual_analysis_works() -> None:
    response = client.post(
        "/v1/decks/analyze",
        json={
            "format": "commander",
            "commander": "Aminatou, the Fateshifter",
            "mainboard": [
                {"name": "Sol Ring", "quantity": 1},
                {"name": "Arcane Signet", "quantity": 1},
                {"name": "Swords to Plowshares", "quantity": 1},
                {"name": "Ponder", "quantity": 1},
                {"name": "Preordain", "quantity": 1},
                {"name": "Oath of Kaya", "quantity": 1},
                {"name": "Narset, Parter of Veils", "quantity": 1},
                {"name": "Island", "quantity": 33},
                {"name": "Plains", "quantity": 30},
                {"name": "Swamp", "quantity": 30},
            ],
            "notes": "Explain how this commander deck will play.",
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["commander"] == "Aminatou, the Fateshifter"
    assert payload["validation"]
    assert payload["advice"]["watch_out_for"]
    assert payload["package_observations"]


def test_analyze_response_carries_honest_provenance() -> None:
    response = client.post(
        "/v1/decks/analyze",
        json={
            "format": "modern",
            "mainboard": [{"name": "Lightning Bolt", "quantity": 4}, {"name": "Mountain", "quantity": 56}],
            "sideboard": [],
            "deep_analysis": False,
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert "provenance" in payload
    provenance = payload["provenance"]
    assert provenance["source_type"] in {"corpus", "hybrid", "fallback"}
    assert 0 <= provenance["confidence"] <= 1
    assert isinstance(provenance["retrieved_from"], list)
    # deep_analysis=False must never advertise that the LLM was used.
    assert payload["deep_analysis_used"] is False
    assert payload["ai_coaching_note"] == ""


def test_invalid_manual_deck_analysis_still_returns_feedback() -> None:
    response = client.post(
        "/v1/decks/analyze",
        json={
            "format": "modern",
            "mainboard": [{"name": "Lightning Bolt", "quantity": 8}],
            "sideboard": [],
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["validation"]["is_legal"] is False
    assert payload["weaknesses"]


def test_explicit_narrow_color_commander_only_contains_legal_cards() -> None:
    """Regression: Eris (R/U) used to inherit Sliver (5C) packages and end up with
    Forest/Plains/Swamp. Color identity must be enforced end-to-end."""
    response = client.post(
        "/v1/decks/generate",
        json={
            "format": "commander",
            "commander_name": "Eris, Roar of the Storm",
            "playstyle_tags": ["spells"],
            "theme_tags": [],
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["commander"] == "Eris, Roar of the Storm"
    assert set(payload["colors"]) == {"R", "U"}
    assert payload["is_legal"] is True
    assert payload["validation_errors"] == []
    forbidden = {"Forest", "Plains", "Swamp"}
    leaked = [card for card in payload["mainboard"] if card["name"] in forbidden]
    assert leaked == [], f"off-color basics leaked: {leaked}"


def test_explicit_commander_provenance_does_not_leak_unrelated_archetypes() -> None:
    """Regression: an explicit commander must not list unrelated retrieved
    archetypes (e.g. Sliver shells) as `source_archetypes`."""
    response = client.post(
        "/v1/decks/generate",
        json={
            "format": "commander",
            "commander_name": "Eris, Roar of the Storm",
            "playstyle_tags": ["spells"],
        },
    )
    assert response.status_code == 200
    payload = response.json()
    # No corpus archetype is keyed to Eris in the sample data, so source_archetypes
    # MUST be empty rather than a list of Sliver-flavored shells.
    assert payload["source_archetypes"] == []
    assert payload["selected_archetype"] is None
    provenance = payload["provenance"]
    assert provenance["source_type"] == "fallback"
    assert provenance["fallback_used"] is True
    assert provenance["confidence"] <= 0.6
    assert provenance["evidence_count"] == 0


def test_provenance_corpus_path_for_format_with_archetypes() -> None:
    response = client.post(
        "/v1/decks/generate",
        json={
            "format": "modern",
            "colors": ["U", "R"],
            "playstyle_tags": ["aggro", "spells"],
            "theme_tags": ["prowess"],
        },
    )
    assert response.status_code == 200
    provenance = response.json()["provenance"]
    assert provenance["source_type"] in {"corpus", "hybrid"}
    assert provenance["fallback_used"] is False
    assert provenance["confidence"] >= 0.4
    assert provenance["evidence_count"] >= 1
    assert provenance["retrieved_from"]


def test_commander_decks_never_contain_off_color_cards() -> None:
    """Light end-to-end fuzz: a few well-known explicit commanders must produce
    legal decks with no off-color cards in the mainboard."""
    cases = [
        ("Aminatou, the Fateshifter", {"W", "U", "B"}),
        ("Eris, Roar of the Storm", {"R", "U"}),
    ]
    for commander_name, identity in cases:
        response = client.post(
            "/v1/decks/generate",
            json={
                "format": "commander",
                "commander_name": commander_name,
            },
        )
        assert response.status_code == 200, f"failed for {commander_name}: {response.text}"
        payload = response.json()
        assert payload["is_legal"], f"{commander_name} produced illegal deck: {payload['validation_errors']}"
        assert payload["validation_errors"] == [], commander_name
        for card in payload["mainboard"]:
            detail = client.get(f"/v1/cards/{card['name']}").json().get("card")
            if not detail:
                continue
            card_identity = set(detail["color_identity"]) or set(detail["colors"])
            assert card_identity.issubset(identity) or not card_identity, (
                f"{commander_name}: {card['name']} has identity {card_identity} not in {identity}"
            )


def test_constructed_narrow_color_request_excludes_off_color_lands() -> None:
    """Regression: a mono-R modern request used to receive Spirebluff Canal
    and Steam Vents (UR lands) when the strict color filter fell back to a
    UR shell. Lands must respect the requested color identity in every format,
    not just commander."""
    response = client.post(
        "/v1/decks/generate",
        json={
            "format": "modern",
            "colors": ["R"],
            "playstyle_tags": ["aggro"],
            "theme_tags": [],
            "prompt": "max aggressive mono-red burn",
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["colors"] == ["R"]
    forbidden = {"Spirebluff Canal", "Steam Vents", "Watery Grave", "Hallowed Fountain", "Stomping Ground"}
    leaked = [card for card in payload["mainboard"] if card["name"] in forbidden]
    assert leaked == [], f"off-color lands leaked into mono-R deck: {leaked}"


def test_constructed_narrow_color_request_does_not_pull_superset_archetype() -> None:
    """End-to-end: a 2-color modern request should retrieve a shell whose colors
    are a subset of the request, not a 3- or 5-color shell that happens to have
    high source_count."""
    response = client.post(
        "/v1/decks/generate",
        json={
            "format": "modern",
            "colors": ["U", "R"],
            "playstyle_tags": ["aggro", "spells"],
            "theme_tags": ["prowess"],
        },
    )
    assert response.status_code == 200
    payload = response.json()
    selected = payload["selected_archetype"]
    assert selected is not None
    assert set(selected["colors"]).issubset({"U", "R"}), selected["colors"]
    for retrieved in payload["source_archetypes"]:
        # Each retrieved shell name is just a label, but the deck colors must
        # not have silently expanded beyond the request.
        assert retrieved
    assert set(payload["colors"]).issubset({"U", "R"})


def test_score_breakdown_does_not_expose_fake_fields() -> None:
    """Regression: prompt_fit and budget_fit were hardcoded to 0; remove them
    so the API does not advertise rigor it isn't actually computing."""
    response = client.post(
        "/v1/decks/generate",
        json={
            "format": "modern",
            "colors": ["U", "R"],
            "playstyle_tags": ["aggro", "spells"],
        },
    )
    assert response.status_code == 200
    score = response.json()["score"]
    assert "prompt_fit" not in score
    assert "budget_fit" not in score
    assert "legality" in score
    assert "total" in score


def test_manual_analysis_exact_swaps_use_specific_cards() -> None:
    response = client.post(
        "/v1/decks/analyze",
        json={
            "format": "modern",
            "mainboard": [
                {"name": "Monastery Swiftspear", "quantity": 4},
                {"name": "Lightning Bolt", "quantity": 4},
                {"name": "Mountain", "quantity": 20},
                {"name": "Goblin Guide", "quantity": 4},
                {"name": "Shock", "quantity": 4},
                {"name": "Lava Spike", "quantity": 4},
                {"name": "Rift Bolt", "quantity": 4},
                {"name": "Skewer the Critics", "quantity": 4},
                {"name": "Needle Drop", "quantity": 4},
                {"name": "Reckless Impulse", "quantity": 4},
                {"name": "Wizard's Lightning", "quantity": 4},
            ],
            "sideboard": [],
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["swap_recommendations"]
    assert any(item["category"] in {"Shell Alignment", "Interaction", "Draw", "Threat", "Engine"} for item in payload["swap_recommendations"])
    assert all(item["cut_card"] != item["add_card"] for item in payload["swap_recommendations"])
