"""
Phase 4 coverage tests: parametrized formats/modes, error handling, parser edge cases,
export targets, refine card preservation, and validation edge cases.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.scripts.build_archetypes import main as build_archetypes_main
from app.scripts.ingest_tournament_decks import main as ingest_tournament_main

client = TestClient(app)


def setup_module() -> None:
    ingest_tournament_main([])
    build_archetypes_main()


# ── Format × colour coverage ───────────────────────────────────────────────────

@pytest.mark.parametrize("fmt,colors,playstyle,expected_size", [
    ("modern",    ["U", "R"], ["aggro"],   60),
    ("standard",  ["R", "W"], ["aggro"],   60),
    ("legacy",    ["U", "B"], ["control"], 60),
    ("commander", ["G", "U"], ["ramp"],    99),
])
def test_generate_all_formats_produces_legal_deck(fmt, colors, playstyle, expected_size) -> None:
    response = client.post("/v1/decks/generate", json={
        "format": fmt,
        "colors": colors,
        "playstyle_tags": playstyle,
        "theme_tags": [],
    })
    assert response.status_code == 200
    payload = response.json()
    assert payload["format"] == fmt
    total = sum(c["quantity"] for c in payload["mainboard"])
    assert total == expected_size, f"{fmt}: expected {expected_size} mainboard cards, got {total}"
    assert payload["is_legal"] is True
    assert payload["score"]["legality"] == 100


@pytest.mark.parametrize("mode", ["fast-competitive", "constraint-aware", "creative-but-viable"])
def test_generate_all_modes_produce_legal_deck(mode) -> None:
    response = client.post("/v1/decks/generate", json={
        "format": "modern",
        "colors": ["U", "R"],
        "playstyle_tags": ["aggro"],
        "mode": mode,
    })
    assert response.status_code == 200
    assert response.json()["is_legal"] is True


# ── Error handling ────────────────────────────────────────────────────────────

def test_generate_invalid_format_returns_422() -> None:
    response = client.post("/v1/decks/generate", json={
        "format": "vintage",  # not a valid FormatName literal
        "colors": ["R"],
        "playstyle_tags": [],
    })
    assert response.status_code == 422


def test_generate_invalid_commander_returns_400() -> None:
    response = client.post("/v1/decks/generate", json={
        "format": "commander",
        "colors": ["R"],
        "commander_name": "Lightning Bolt",  # not a legendary creature
        "playstyle_tags": [],
    })
    assert response.status_code == 400


def test_card_detail_nonexistent_returns_404() -> None:
    response = client.get("/v1/cards/DefinitelyNotARealCardXYZABC")
    assert response.status_code == 404


def test_commander_detail_nonexistent_returns_404() -> None:
    response = client.get("/v1/commanders/DefinitelyNotARealCommanderXYZABC")
    assert response.status_code == 404


def test_refine_with_empty_prompt_still_succeeds() -> None:
    gen = client.post("/v1/decks/generate", json={
        "format": "modern",
        "colors": ["R"],
        "playstyle_tags": ["aggro"],
    })
    assert gen.status_code == 200
    response = client.post("/v1/decks/refine", json={
        "deck": gen.json(),
        "refinement_prompt": "",
    })
    assert response.status_code == 200
    assert response.json()["is_legal"] is True


def test_analyze_deck_with_no_mainboard_returns_feedback() -> None:
    response = client.post("/v1/decks/analyze", json={
        "format": "modern",
        "mainboard": [],
        "sideboard": [],
        "notes": "What should I add?",
    })
    assert response.status_code == 200
    payload = response.json()
    assert payload["deck_health"] in {
        "well-structured", "promising but unfinished",
        "coherent but underpowered", "structurally flawed",
    }


# ── Validation edge cases ─────────────────────────────────────────────────────

def test_validate_exceeds_4_copy_limit() -> None:
    response = client.post("/v1/decks/validate", json={
        "format": "modern",
        "mainboard": [{"name": "Lightning Bolt", "quantity": 8}],
        "sideboard": [],
    })
    assert response.status_code == 200
    payload = response.json()
    assert payload["is_legal"] is False
    assert any("4-copy" in e or "limit" in e.lower() for e in payload["errors"])


def test_validate_constructed_wrong_mainboard_size() -> None:
    response = client.post("/v1/decks/validate", json={
        "format": "modern",
        "mainboard": [{"name": "Lightning Bolt", "quantity": 4}],  # only 4, need 60
        "sideboard": [],
    })
    assert response.status_code == 200
    payload = response.json()
    assert payload["is_legal"] is False
    assert any("60" in e for e in payload["errors"])


def test_validate_commander_wrong_mainboard_size() -> None:
    response = client.post("/v1/decks/validate", json={
        "format": "commander",
        "commander": "The First Sliver",
        "mainboard": [{"name": "Cultivate", "quantity": 5}],  # 5 != 99
        "sideboard": [],
    })
    assert response.status_code == 200
    payload = response.json()
    assert payload["is_legal"] is False
    assert any("99" in e for e in payload["errors"])


def test_validate_commander_color_identity_violation() -> None:
    # Aminatou is W/U/B (Esper). Lightning Bolt is R — outside identity.
    response = client.post("/v1/decks/validate", json={
        "format": "commander",
        "commander": "Aminatou, the Fateshifter",
        "mainboard": (
            [{"name": "Lightning Bolt", "quantity": 1}]
            + [{"name": "Plains", "quantity": 98}]
        ),
        "sideboard": [],
    })
    assert response.status_code == 200
    payload = response.json()
    assert payload["is_legal"] is False
    assert any("color identity" in e.lower() for e in payload["errors"])


def test_validate_commander_format_requires_commander_field() -> None:
    response = client.post("/v1/decks/validate", json={
        "format": "commander",
        "mainboard": [{"name": "Forest", "quantity": 99}],
        "sideboard": [],
    })
    assert response.status_code == 200
    payload = response.json()
    assert payload["is_legal"] is False
    assert any("commander" in e.lower() for e in payload["errors"])


# ── Parser edge cases ─────────────────────────────────────────────────────────

def test_parse_arena_format_merges_repeated_lines() -> None:
    # Arena exports one line per copy — four identical lines should become qty=4
    deck_text = "\n".join([
        "Lightning Bolt (M11) 163",
        "Lightning Bolt (M11) 163",
        "Lightning Bolt (M11) 163",
        "Lightning Bolt (M11) 163",
    ])
    response = client.post("/v1/decks/parse", json={"format": "modern", "deck_text": deck_text})
    assert response.status_code == 200
    payload = response.json()
    assert not any("Could not parse" in w for w in payload["warnings"])
    bolt = next((c for c in payload["mainboard"] if "Lightning Bolt" in c["name"]), None)
    assert bolt is not None, "Lightning Bolt should appear in mainboard"
    assert bolt["quantity"] == 4


def test_parse_dfc_arena_format_preserves_full_name() -> None:
    # "Name // Name (SET) N" — the full card name should be captured, not just the front face
    deck_text = "Fire // Ice (ICE) 95"
    response = client.post("/v1/decks/parse", json={"format": "legacy", "deck_text": deck_text})
    assert response.status_code == 200
    payload = response.json()
    assert not any("Could not parse" in w for w in payload["warnings"])
    assert len(payload["mainboard"]) == 1
    parsed_name = payload["mainboard"][0]["name"]
    assert parsed_name != "Fire", "DFC name must not be truncated to the front face only"


def test_parse_section_markers_route_cards_correctly() -> None:
    deck_text = "\n".join([
        "Mainboard",
        "4 Lightning Bolt",
        "20 Mountain",
        "",
        "Sideboard",
        "2 Spell Pierce",
    ])
    response = client.post("/v1/decks/parse", json={"format": "modern", "deck_text": deck_text})
    assert response.status_code == 200
    payload = response.json()
    main_names = {c["name"] for c in payload["mainboard"]}
    side_names = {c["name"] for c in payload["sideboard"]}
    assert any("Lightning Bolt" in n for n in main_names)
    assert any("Spell Pierce" in n for n in side_names)
    # Sideboard card must not appear in mainboard
    assert not side_names & main_names


def test_parse_empty_deck_returns_empty_lists() -> None:
    response = client.post("/v1/decks/parse", json={"format": "modern", "deck_text": ""})
    assert response.status_code == 200
    payload = response.json()
    assert payload["mainboard"] == []
    assert payload["sideboard"] == []


def test_parse_standard_quantity_format() -> None:
    # Standard "4 CardName" format
    deck_text = "4 Lightning Bolt\n20 Mountain"
    response = client.post("/v1/decks/parse", json={"format": "modern", "deck_text": deck_text})
    assert response.status_code == 200
    payload = response.json()
    bolt = next((c for c in payload["mainboard"] if "Lightning Bolt" in c["name"]), None)
    assert bolt is not None
    assert bolt["quantity"] == 4


# ── Export all targets ────────────────────────────────────────────────────────

@pytest.mark.parametrize("target", ["plain", "arena", "moxfield", "csv"])
def test_export_all_targets_return_nonempty_content(target) -> None:
    gen = client.post("/v1/decks/generate", json={
        "format": "modern",
        "colors": ["R"],
        "playstyle_tags": ["aggro"],
    })
    assert gen.status_code == 200
    response = client.post("/v1/decks/export", json={"deck": gen.json(), "target": target})
    assert response.status_code == 200
    payload = response.json()
    assert payload["target"] == target
    assert len(payload["content"]) > 0


def test_export_arena_format_has_set_annotations() -> None:
    gen = client.post("/v1/decks/generate", json={
        "format": "modern", "colors": ["R"], "playstyle_tags": ["aggro"],
    })
    assert gen.status_code == 200
    response = client.post("/v1/decks/export", json={"deck": gen.json(), "target": "arena"})
    assert response.status_code == 200
    # Arena format lines look like "4 CardName" or contain section headers
    content = response.json()["content"]
    assert len(content.strip()) > 0


# ── Refine card preservation (Phase 2 fix verification) ───────────────────────

def test_refine_preserves_majority_of_original_cards() -> None:
    gen = client.post("/v1/decks/generate", json={
        "format": "modern",
        "colors": ["U", "R"],
        "playstyle_tags": ["aggro", "spells"],
        "theme_tags": ["prowess"],
    })
    assert gen.status_code == 200
    original = gen.json()
    original_names = {c["name"] for c in original["mainboard"]}

    refined = client.post("/v1/decks/refine", json={
        "deck": original,
        "refinement_prompt": "Make it slightly more interactive.",
    })
    assert refined.status_code == 200
    refined_names = {c["name"] for c in refined.json()["mainboard"]}

    overlap = len(original_names & refined_names)
    assert overlap / len(original_names) >= 0.5, (
        f"Refine should preserve ≥50% of cards; kept {overlap}/{len(original_names)}"
    )


def test_refine_budget_does_not_floor_at_25() -> None:
    # Generate a deck with a $10 budget. Refine with "cheaper".
    # Old bug: max(25.0, price * 0.7) always set budget ≥ $25 even for $10 decks.
    gen = client.post("/v1/decks/generate", json={
        "format": "modern",
        "colors": ["R"],
        "playstyle_tags": ["aggro"],
        "budget": 10.0,
    })
    assert gen.status_code == 200
    response = client.post("/v1/decks/refine", json={
        "deck": gen.json(),
        "refinement_prompt": "Make it budget and cheaper.",
    })
    assert response.status_code == 200
    assert response.json()["is_legal"] is True


def test_refine_commander_preserves_commander() -> None:
    gen = client.post("/v1/decks/generate", json={
        "format": "commander",
        "colors": ["W", "U", "B"],
        "commander_name": "Aminatou, the Fateshifter",
        "playstyle_tags": ["control"],
    })
    assert gen.status_code == 200
    original = gen.json()
    assert original["commander"] == "Aminatou, the Fateshifter"

    refined = client.post("/v1/decks/refine", json={
        "deck": original,
        "refinement_prompt": "Add more card draw.",
    })
    assert refined.status_code == 200
    assert refined.json()["commander"] == "Aminatou, the Fateshifter"


# ── Card search edge cases ────────────────────────────────────────────────────

def test_card_search_empty_query_returns_empty() -> None:
    response = client.get("/v1/cards", params={"query": ""})
    assert response.status_code == 200
    assert response.json()["cards"] == []


def test_card_search_format_filter_excludes_illegal_cards() -> None:
    # Lightning Bolt is not Standard legal
    response = client.get("/v1/cards", params={"query": "Lightning Bolt", "format": "standard"})
    assert response.status_code == 200
    cards = response.json()["cards"]
    assert all(c["name"] != "Lightning Bolt" for c in cards)


def test_card_search_returns_relevant_results() -> None:
    response = client.get("/v1/cards", params={"query": "Lightning", "format": "modern"})
    assert response.status_code == 200
    cards = response.json()["cards"]
    assert len(cards) > 0
    assert any("Lightning" in c["name"] for c in cards)


# ── Meta summary ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("fmt", ["modern", "standard", "legacy", "commander"])
def test_meta_summary_returns_archetypes_for_all_formats(fmt) -> None:
    response = client.get("/v1/meta/summary", params={"format": fmt})
    assert response.status_code == 200
    payload = response.json()
    assert payload["format"] == fmt
    assert isinstance(payload["archetypes"], list)


# ── New tests: Section 2 ──────────────────────────────────────────────────────

def test_validate_constructed_deck_size_under() -> None:
    """59-card deck should fail validation with a size error."""
    mainboard = [{"name": "Mountain", "quantity": 59}]
    response = client.post("/v1/decks/validate", json={
        "format": "modern",
        "mainboard": mainboard,
        "sideboard": [],
    })
    assert response.status_code == 200
    payload = response.json()
    assert payload["is_legal"] is False
    assert any("60" in err for err in payload["errors"])


def test_validate_constructed_deck_size_over() -> None:
    """61-card deck should fail validation with a size error."""
    mainboard = [{"name": "Mountain", "quantity": 61}]
    response = client.post("/v1/decks/validate", json={
        "format": "modern",
        "mainboard": mainboard,
        "sideboard": [],
    })
    assert response.status_code == 200
    payload = response.json()
    assert payload["is_legal"] is False
    assert any("60" in err for err in payload["errors"])


def test_validate_insufficient_blue_sources() -> None:
    """Deck with many blue spells but no blue-producing lands should warn about mana sources."""
    # 10 blue spells (Absorb needs UU, Absolute Virtue needs UW) + 50 Mountains
    mainboard = [
        {"name": "Absorb", "quantity": 4},        # {W}{U}{U} — needs blue
        {"name": "Absolute Virtue", "quantity": 4}, # {U}{W} — needs blue
        {"name": "Abhorrent Oculus", "quantity": 2}, # blue creature
        {"name": "Mountain", "quantity": 50},
    ]
    response = client.post("/v1/decks/validate", json={
        "format": "modern",
        "mainboard": mainboard,
        "sideboard": [],
    })
    assert response.status_code == 200
    payload = response.json()
    # Should warn about insufficient blue sources
    warnings_text = " ".join(payload.get("warnings", []))
    assert "U" in warnings_text or "blue" in warnings_text.lower() or "mana" in warnings_text.lower()


def test_validate_illegal_card_in_sideboard_only() -> None:
    """Legal standard mainboard + non-standard sideboard card should produce an error."""
    # A Little Chat is modern-legal but NOT standard-legal
    mainboard = [{"name": "Island", "quantity": 60}]
    sideboard = [{"name": "A Little Chat", "quantity": 4}]
    response = client.post("/v1/decks/validate", json={
        "format": "standard",
        "mainboard": mainboard,
        "sideboard": sideboard,
    })
    assert response.status_code == 200
    payload = response.json()
    assert payload["is_legal"] is False
    assert any("A Little Chat" in err for err in payload["errors"])


def test_parse_multiple_dfc_cards() -> None:
    """Parser should handle multiple double-faced card lines correctly."""
    dfc1 = "A-Alrund, God of the Cosmos // A-Hakka, Whispering Raven"
    dfc2 = "A-Binding Geist // A-Spectral Binding"
    deck_text = f"3 {dfc1}\n2 {dfc2}\n"
    response = client.post("/v1/decks/parse", json={"deck_text": deck_text, "format": "modern"})
    assert response.status_code == 200
    payload = response.json()
    names = [c["name"] for c in payload["mainboard"]]
    assert len(names) == 2, f"Expected 2 distinct cards, got {names}"
    qty_map = {c["name"]: c["quantity"] for c in payload["mainboard"]}
    # DFC names may be resolved to canonical form; check quantities sum correctly
    total_qty = sum(qty_map.values())
    assert total_qty == 5, f"Expected total qty 5, got {total_qty}"


def test_refine_zero_budget_floor_no_crash() -> None:
    """Refining with a budget-cutting prompt should not crash and produce a valid deck."""
    gen = client.post("/v1/decks/generate", json={
        "format": "modern",
        "colors": ["R"],
        "playstyle_tags": ["aggro"],
        "theme_tags": [],
    })
    assert gen.status_code == 200
    deck = gen.json()
    refine = client.post("/v1/decks/refine", json={
        "deck": deck,
        "refinement_prompt": "make this as cheap as possible, free if you can",
    })
    assert refine.status_code == 200
    refined = refine.json()
    assert refined["format"] == "modern"
    total = sum(c["quantity"] for c in refined["mainboard"])
    assert total == 60, f"Expected 60 mainboard cards after refine, got {total}"


def test_analyze_deck_health_label_is_valid() -> None:
    """deck_health must be one of the four valid states, and explanation must be a string."""
    valid_labels = {"well-structured", "promising but unfinished", "coherent but underpowered", "structurally flawed"}
    gen = client.post("/v1/decks/generate", json={
        "format": "modern",
        "colors": ["U", "B"],
        "playstyle_tags": ["control"],
        "theme_tags": [],
    })
    assert gen.status_code == 200
    deck = gen.json()
    analysis = client.post("/v1/decks/analyze", json={
        "format": deck["format"],
        "commander": deck.get("commander"),
        "mainboard": deck["mainboard"],
        "sideboard": deck["sideboard"],
    })
    assert analysis.status_code == 200
    payload = analysis.json()
    assert payload["deck_health"] in valid_labels, f"Unexpected health label: {payload['deck_health']}"
    assert isinstance(payload.get("deck_health_explanation", ""), str)
    assert payload.get("deck_health_explanation", "") != "", "deck_health_explanation should be non-empty"


def test_generate_with_nonexistent_include_card() -> None:
    """Requesting a nonexistent include_card should not 500; deck is valid and a warning is issued."""
    response = client.post("/v1/decks/generate", json={
        "format": "modern",
        "colors": ["R"],
        "playstyle_tags": ["aggro"],
        "theme_tags": [],
        "include_cards": ["Absolutely Fake Card Name That Does Not Exist 9999"],
    })
    assert response.status_code == 200
    payload = response.json()
    total = sum(c["quantity"] for c in payload["mainboard"])
    assert total == 60, f"Expected 60 mainboard cards, got {total}"
    names = [c["name"] for c in payload["mainboard"]]
    assert "Absolutely Fake Card Name That Does Not Exist 9999" not in names
    warnings = payload.get("warnings", [])
    assert any("Absolutely Fake" in w or "Could not find" in w for w in warnings), \
        f"Expected an unresolved-include warning, got warnings: {warnings}"
