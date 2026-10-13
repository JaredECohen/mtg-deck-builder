"""Spec-gap engine behaviour (docs/IMPLEMENTATION-PLAN-2026-10-12.md, stream A)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app, repository
from app.models import CardRecord
from app.rules import is_land_card

client = TestClient(app)


def _generate(**body) -> dict:
    response = client.post("/v1/decks/generate", json=body)
    assert response.status_code == 200, response.text
    return response.json()


def _names(deck: dict, section: str = "mainboard") -> set[str]:
    return {ref["name"] for ref in deck[section]}


def _count(refs: list[dict]) -> int:
    return sum(ref["quantity"] for ref in refs)


# ── A13: name lookup ─────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("typed", "canonical"),
    [
        ("Lim-Dul's Vault", "Lim-Dûl's Vault"),
        ("Æther Vial", "Aether Vial"),
        ("Fable of the Mirror-Breaker", "Fable of the Mirror-Breaker // Reflection of Kiki-Jiki"),
        ("Reflection of Kiki-Jiki", "Fable of the Mirror-Breaker // Reflection of Kiki-Jiki"),
    ],
)
def test_spelling_variants_and_face_names_resolve(typed, canonical):
    card = repository.get_card(typed)
    assert card is not None and card.name == canonical


def test_ascii_spelling_validates():
    response = client.post("/v1/decks/validate", json={
        "format": "legacy",
        "mainboard": [{"name": "Lim-Dul's Vault", "quantity": 1}, {"name": "Swamp", "quantity": 59}],
    })
    assert not any("Unknown card" in error for error in response.json()["errors"])


# ── A14: MDFC land counting ──────────────────────────────────────────────


def test_spell_land_mdfc_counts_as_a_spell():
    spell_land = CardRecord(name="X // Y", type_line="Instant // Land")
    land_land = CardRecord(name="A // B", type_line="Land // Land")
    assert not is_land_card(spell_land)
    assert is_land_card(land_land)


# ── A2: includes, excludes, budget ───────────────────────────────────────


def test_commander_honors_includes_and_reports_dropped_ones():
    deck = _generate(
        format="commander",
        commander_name="Atraxa, Praetors' Voice",
        include_cards=["Doubling Season", "Lightning Bolt", "Totally Fake Card", "Black Lotus"],
    )
    assert "Doubling Season" in _names(deck)
    dropped = {item["name"]: item["reason"] for item in deck["provenance"]["dropped_includes"]}
    assert dropped == {"Lightning Bolt": "off_color", "Totally Fake Card": "unknown", "Black Lotus": "not_legal"}
    assert any("Lightning Bolt" in warning for warning in deck["warnings"])


def test_excluded_card_never_lands_in_the_sideboard():
    base = _generate(format="modern", colors=["R"], playstyle_tags=["aggro"])
    victim = base["sideboard"][0]["name"]
    deck = _generate(format="modern", colors=["R"], playstyle_tags=["aggro"], exclude_cards=[victim])
    assert victim not in _names(deck, "sideboard") | _names(deck)


def test_budget_build_swaps_or_drops_expensive_anchors_and_respects_the_cap():
    deck = _generate(format="modern", prompt="modern murktide", budget=80)
    assert deck["estimated_price_usd"] is not None and deck["estimated_price_usd"] <= 80
    for swap in deck["provenance"]["budget_substitutions"]:
        assert swap["replacement"] in _names(deck) | _names(deck, "sideboard")


def test_anchor_lands_do_not_bypass_the_budget():
    deck = _generate(format="modern", prompt="modern burn", budget=40)
    for ref in deck["mainboard"]:
        card = repository.get_card(ref["name"])
        if card is not None and is_land_card(card) and card.price_usd is not None:
            assert card.price_usd <= 40 * 0.12, ref


# ── A3: sideboards ───────────────────────────────────────────────────────


@pytest.mark.parametrize("fmt", ["standard", "pioneer", "modern", "legacy"])
def test_best_of_three_decks_get_a_full_sideboard(fmt):
    deck = _generate(format=fmt, colors=["W", "U"], playstyle_tags=["control"])
    assert _count(deck["sideboard"]) == 15
    assert deck["is_legal"], deck["validation_errors"]


def test_best_of_one_has_no_sideboard():
    deck = _generate(format="modern", colors=["R"], playstyle_tags=["aggro"], match_type="bo1")
    assert deck["sideboard"] == []
    assert deck["constraints"]["match_type"] == "bo1"


# ── A7: Commander brackets ───────────────────────────────────────────────


def test_bracket_assessment_reads_game_changers_combos_and_mld():
    from app.services.brackets import assess

    casual = assess(["Sol Ring", "Llanowar Elves", "Forest"], repository)
    assert casual.estimated == 2 and not casual.game_changers
    upgraded = assess(["Rhystic Study", "Smothering Tithe", "Forest"], repository)
    assert upgraded.estimated == 3 and upgraded.game_changers == ["Rhystic Study", "Smothering Tithe"]
    optimized = assess(["Armageddon", "Thassa's Oracle", "Demonic Consultation"], repository)
    assert optimized.estimated == 4
    assert optimized.mass_land_denial == ["Armageddon"]
    assert ["Thassa's Oracle", "Demonic Consultation"] in optimized.two_card_combos
    assert optimized.game_changers_as_of


@pytest.mark.parametrize("bracket", [1, 2])
def test_low_bracket_build_has_no_game_changers_or_combos(bracket):
    deck = _generate(format="commander", colors=["U", "B"], playstyle_tags=["control"], bracket=bracket)
    assert deck["bracket"] is not None
    assert deck["bracket"]["target"] == bracket
    assert deck["bracket"]["game_changers"] == []
    assert deck["bracket"]["mass_land_denial"] == []
    assert deck["bracket"]["two_card_combos"] == []


def test_bracket_three_allows_requested_game_changers_only():
    deck = _generate(
        format="commander", colors=["U", "B"], playstyle_tags=["control"], bracket=3,
        include_cards=["Rhystic Study"],
    )
    assert set(deck["bracket"]["game_changers"]) <= {"Rhystic Study"}
    assert "Rhystic Study" in _names(deck)


# ── A6: game plan ────────────────────────────────────────────────────────


@pytest.mark.parametrize("fmt", ["standard", "modern", "commander"])
def test_every_deck_gets_a_game_plan(fmt):
    body = {"format": fmt, "colors": ["R", "G"], "playstyle_tags": ["aggro"]}
    deck = _generate(**body)
    plan = deck["game_plan"]
    assert plan["summary"] and plan["win_conditions"] and plan["opening_hand"] and plan["mulligan"]
    in_deck = _names(deck) | ({deck["commander"]} if deck["commander"] else set())
    assert set(plan["win_conditions"]) <= in_deck
    if fmt != "commander":
        guided = {entry["card"] for entry in plan["sideboard_guide"]}
        assert guided == _names(deck, "sideboard")
        assert all(entry["take_out"] for entry in plan["sideboard_guide"])
    else:
        assert plan["commander_packages"]


# ── A8 / A9: modes, alternatives, archetype_name; deterministic refine ───


def test_creative_mode_varies_the_flex_slots_and_stays_legal():
    base = dict(format="commander", colors=["B", "G"], playstyle_tags=["graveyard"])
    standard = _generate(**base)
    creative = _generate(**base, mode="creative-but-viable")
    assert creative["is_legal"], creative["validation_errors"]
    assert _names(creative) != _names(standard)


def test_alternatives_can_be_built_by_name():
    deck = _generate(format="modern", colors=["R"], playstyle_tags=["aggro"])
    assert 1 <= len(deck["alternatives"]) <= 2
    alternative = deck["alternatives"][0]
    built = _generate(format="modern", colors=["R"], playstyle_tags=["aggro"], archetype_name=alternative["name"])
    assert alternative["name"].lower() in built["title"].lower()
    assert built["is_legal"]


@pytest.mark.parametrize(
    ("prompt", "includes", "excludes", "quantities"),
    [
        ("add 4x Burst Lightning", ["Burst Lightning"], [], {"Burst Lightning": 4}),
        ("Swap Swan Song for 4 Burst Lightning", ["Burst Lightning"], ["Swan Song"], {"Burst Lightning": 4}),
        ("cut Lava Dart, add 2 Lightning Helix", ["Lightning Helix"], ["Lava Dart"], {"Lightning Helix": 2}),
        ("Add a playset of Lightning Helix", ["Lightning Helix"], [], {"Lightning Helix": 4}),
        ("make it cheaper", [], [], {}),
    ],
)
def test_refine_reads_card_names_without_an_llm(prompt, includes, excludes, quantities):
    from app.main import generator

    assert generator._parse_refine_cards(prompt) == (includes, excludes, quantities)


def test_no_llm_refine_adds_the_requested_copies():
    deck = _generate(format="modern", colors=["R"], playstyle_tags=["aggro"])
    response = client.post("/v1/decks/refine", json={"deck": deck, "refinement_prompt": "add 4x Burst Lightning"})
    assert response.status_code == 200, response.text
    refined = response.json()
    assert sum(r["quantity"] for r in refined["mainboard"] if r["name"] == "Burst Lightning") == 4
    assert refined["changes"]["summary"]["total_changes"] > 0


# ── A11: corpus honesty ──────────────────────────────────────────────────


def test_no_archetype_claims_an_absurd_land_package():
    for archetype in repository.all_archetypes():
        for package in archetype.metadata.land_packages:
            assert (package.average_quantity or 0) <= 40, (archetype.name, package.name, package.average_quantity)


def test_synthesized_shells_are_labelled_template():
    deck = _generate(format="commander", colors=["B"], playstyle_tags=["sacrifice"])
    assert deck["provenance"]["source_type"] in {"template", "hybrid", "fallback", "builtin"}
    if deck["provenance"]["source_type"] == "template":
        assert "not observed" in " ".join(deck["explanation"]).lower() or deck["sections"]


# ── A10: titles, A12: optimizer path ─────────────────────────────────────


def test_titles_name_the_colors_actually_played():
    deck = _generate(format="modern", colors=["R"], playstyle_tags=["aggro"])
    assert deck["title"].split()[0] in {"Mono-Red", "Modern"}
    assert "RU" not in deck["title"] and "Izzet" not in deck["title"]
    title = _generate(format="standard", colors=["W", "U"], playstyle_tags=["control"])["title"]
    assert title.split().count("Control") <= 1


def test_optimizer_default_path_is_legal_and_on_budget(monkeypatch):
    monkeypatch.setenv("MTG_USE_OPTIMIZER_DEFAULT", "1")
    deck = _generate(format="modern", colors=["R"], playstyle_tags=["aggro"], budget=60)
    assert deck["is_legal"], deck["validation_errors"]
    assert deck["estimated_price_usd"] is None or deck["estimated_price_usd"] <= 60
    assert any("imulator" in note for note in deck["provenance"]["notes"])
    assert sum(ref["quantity"] for ref in deck["sideboard"]) == 15


# ── A16 land ranges, A17 collection ──────────────────────────────────────


def test_low_curve_aggro_is_not_told_it_needs_more_lands():
    deck = _generate(format="modern", prompt="modern burn")
    assert not any("Land count looks low" in w for w in deck["warnings"]), deck["warnings"]


def test_owned_cards_are_preferred_and_free_against_the_budget():
    owned = ["Lightning Bolt", "Goblin Guide", "Monastery Swiftspear", "Eidolon of the Great Revel"]
    deck = _generate(format="modern", colors=["R"], playstyle_tags=["aggro"], owned_cards=owned, budget=40)
    assert set(owned) & _names(deck)
    assert deck["cost_to_complete_usd"] is not None
    assert deck["cost_to_complete_usd"] <= 40
    assert deck["constraints"]["owned_cards"] == owned


# ── A15: analysis advice ─────────────────────────────────────────────────

_BURN = [
    {"name": n, "quantity": 4} for n in [
        "Lightning Bolt", "Goblin Guide", "Monastery Swiftspear", "Lava Spike", "Rift Bolt",
        "Skewer the Critics", "Boros Charm", "Eidolon of the Great Revel", "Searing Blaze", "Lightning Helix",
    ]
] + [{"name": "Mountain", "quantity": 12}, {"name": "Sacred Foundry", "quantity": 4}, {"name": "Inspiring Vantage", "quantity": 4}]


def test_aggro_analysis_never_pushes_ramp_or_cuts_playsets_outside_shell_alignment():
    response = client.post("/v1/decks/analyze", json={"format": "modern", "mainboard": _BURN, "deep_analysis": False})
    assert response.status_code == 200, response.text
    body = response.json()
    assert not any("mana development" in line.lower() for line in body["advice"]["add_more_of"])
    for swap in body["swap_recommendations"]:
        assert swap["category"] != "Ramp"
        if swap["category"] != "Shell Alignment":
            assert swap["cut_card"] not in {ref["name"] for ref in _BURN}
        add = repository.get_card(swap["add_card"])
        assert add is not None and set(add.color_identity) <= {"R", "W"}


def test_analysis_name_normalization_folds_accents():
    from app.services.deck_analysis import _norm

    assert _norm("Lim-Dûl's Vault") == _norm("Lim-Dul's Vault")
    assert _norm("Æther Vial") == _norm("Aether Vial")
